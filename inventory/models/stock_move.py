"""
stock.move / stock.move.line, with Odoo's state machine and chain structure.

  Status:  DRAFT -> CONFIRMED | WAITING -> PARTIALLY_AVAILABLE -> ASSIGNED -> COMPLETED
                                                                      \\-> CANCELLED (from any open state)
  Chain:   move_dest_ids / move_orig_ids (M2M). A pick feeds a ship: pick.move_dest_ids = {ship}.
  Demand:  StockMove.quantity (in product_uom).   Execution: StockMoveLine.

Odoo method mapping (set operations live on the queryset, like Odoo recordsets):
  _action_confirm -> StockMove.objects...action_confirm() / move.confirm()
  _action_assign  -> ...action_assign()        / move.assign()
  _action_done    -> move.complete()
  _action_cancel  -> move.cancel()
  _push_apply     -> ...push_apply()           _assign_picking -> ...assign_picking()
  _recompute_state-> move._recompute_state()
"""
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from inventory.models import StockLocation


class StockMoveQuerySet(models.QuerySet):

    # ------------------------------------------------------------------ confirm
    @transaction.atomic
    def action_confirm(self):
        """Odoo's _action_confirm for DRAFT moves.

        1. MTO moves with nothing feeding them ask their SOURCE location for supply
           (ProcurementGroup.run with move_dest_ids=[move]); this is how pull chains form.
        2. State is derived: WAITING while a feeding move is open, ASSIGNED for moves that bypass
           reservation (receipts), otherwise CONFIRMED.
        3. Push rules are applied (a transparent push may change the destination, so this happens
           before pickings are assigned); new push moves are confirmed too.
        4. Moves without a picking are assigned to one."""
        from inventory.models import ProcurementGroup

        moves = [m for m in self.select_related("product", "picking", "source_location", "dest_location")
                 if m.status == StockMove.Status.DRAFT]
        if not moves:
            return self

        create_proc = [m for m in moves
                       if not m.move_orig_ids.exists()
                       and m.procure_method == StockMove.ProcureMethod.MAKE_TO_ORDER]
        if create_proc:
            ProcurementGroup.run([m._prepare_procurement() for m in create_proc])

        for m in moves:
            m._set_status(StockMove.Status.CONFIRMED)
            m._recompute_state()

        confirmed = StockMove.objects.filter(pk__in=[m.pk for m in moves])
        new_push = confirmed.push_apply()
        confirmed.assign_picking()
        if new_push:
            StockMove.objects.filter(pk__in=[m.pk for m in new_push]).action_confirm()
        return self

    # ------------------------------------------------------------------ push
    def push_apply(self, _visited=None):
        """Odoo's _push_apply: for each move that is not already chained, find a push rule that
        starts where it ends. Returns the new (draft) push moves."""
        from inventory.models.routes_and_rules import find_push_rule

        visited = _visited if _visited is not None else set()
        new_moves = []
        for move in list(self.select_related("product", "dest_location__warehouse", "warehouse",
                                             "picking__picking_type__warehouse")):
            if move.move_dest_ids.exists():              # already chained: no push
                continue
            warehouse = move.warehouse or move.dest_location.warehouse
            rule = find_push_rule(move.product, move.dest_location, warehouse, move.company,
                                  list(move.routes.all()))
            if rule is None or (move.pk, rule.pk) in visited or move._push_loop(rule):
                continue
            visited.add((move.pk, rule.pk))
            new = rule._run_push(move, visited)
            if new is not None:
                new_moves.append(new)
        return new_moves

    # ------------------------------------------------------------------ pickings
    @transaction.atomic
    def assign_picking(self):
        """Odoo's _assign_picking: moves sharing (group, source, destination, picking type) go on one
        picking: an open picking of the same group if there is one, else a new one. Moves with no
        group never join an existing picking (nothing says they belong together) but moves of the
        same batch still share a new one."""
        from inventory.models import StockPicking

        batches = defaultdict(list)
        for m in self.select_related("group", "picking_type__warehouse", "product"):
            if m.picking_id or not m.picking_type_id or m.status == StockMove.Status.DRAFT:
                continue
            batches[(m.group_id, m.source_location_id, m.dest_location_id, m.picking_type_id)].append(m)

        for moves in batches.values():
            first = moves[0]
            picking = first._search_picking_for_assignation()
            if picking is None:
                picking = StockPicking.objects.create(**first._get_new_picking_values(moves))
            else:
                origins = picking.origin.split(", ") if picking.origin else []
                for m in moves:
                    if m.origin and m.origin not in origins:
                        origins.append(m.origin)
                picking.origin = ", ".join(origins)[:64]
                picking.save(update_fields=["origin"])
            for m in moves:
                m.picking = picking
                m.save(update_fields=["picking"])        # also refreshes the picking
        return self

    # ------------------------------------------------------------------ reservation
    @transaction.atomic
    def action_assign(self, allow_break=False):
        """Odoo's _action_assign: reserve for CONFIRMED / PARTIALLY_AVAILABLE moves, then derive the
        state from what got reserved. Returns {move: shortage}.
        Contract with your allocation engine: it is only called for moves that have no lines yet."""
        from inventory.services.stock_Picking.allocate_stock import allocate_stock_move

        S, short = StockMove.Status, {}
        for move in list(self.select_related("product", "source_location")):
            # A WAITING move can reserve once something it waits for has arrived (Odoo reserves
            # waiting moves too): goods of a partly completed pick must not sit in Output.
            arrived = move.status == S.WAITING and move.move_orig_ids.filter(status=S.COMPLETED).exists()
            if move.status not in (S.CONFIRMED, S.PARTIALLY_AVAILABLE) and not arrived:
                continue
            if not move._should_bypass_reservation and not move.lines.exists():
                result = allocate_stock_move(move, allow_break=allow_break)
                if result.shortage > 0:
                    short[move] = result.shortage
            move._recompute_state()
        return short

    def recompute_state(self):
        for move in list(self):
            move._recompute_state()
        return self

    def action_cancel(self):
        for move in list(self):
            move.cancel()
        return self


class StockMove(models.Model):

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'New'
        WAITING = 'WAITING', 'Waiting Another Move'
        CONFIRMED = 'CONFIRMED', 'Waiting Availability'
        PARTIALLY_AVAILABLE = 'PARTIALLY_AVAILABLE', 'Partially Available'
        ASSIGNED = 'ASSIGNED', 'Available'
        COMPLETED = 'COMPLETED', 'Done'
        CANCELLED = 'CANCELLED', 'Cancelled'

    # confirmed and not finished: what counts as committed demand/supply
    ACTIVE_STATUSES = (Status.WAITING, Status.CONFIRMED, Status.PARTIALLY_AVAILABLE, Status.ASSIGNED)
    OPEN_STATUSES = (Status.DRAFT,) + ACTIVE_STATUSES

    class ProcureMethod(models.TextChoices):
        MAKE_TO_STOCK = 'make_to_stock', 'Take From Stock'
        MAKE_TO_ORDER = 'make_to_order', 'Trigger Another Rule (MTO)'

    objects = StockMoveQuerySet.as_manager()

    # The move type is *derived* from (source usage, destination usage), as in Odoo.
    # Storing it separately lets it contradict the locations.
    _U = StockLocation.Usage
    MOVE_TYPE_BY_USAGE = {
        (_U.SUPPLIER, _U.INTERNAL): 'RECEIPT',
        (_U.INTERNAL, _U.CUSTOMER): 'SALES',
        (_U.CUSTOMER, _U.INTERNAL): 'CUSTOMER RETURN',
        (_U.INTERNAL, _U.SUPPLIER): 'RETURN TO SUPPLIER',
        (_U.INTERNAL, _U.INTERNAL): 'TRANSFER',
        (_U.INTERNAL, _U.TRANSIT): 'TRANSFER',
        (_U.TRANSIT, _U.INTERNAL): 'TRANSFER',
        (_U.INVENTORY, _U.INTERNAL): 'ADJUSTMENT',
        (_U.INTERNAL, _U.INVENTORY): 'ADJUSTMENT',
    }
    del _U

    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='stock_moves')
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='stock_moves',
                                null=True, blank=True, help_text='Defaults to the product company.')
    picking = models.ForeignKey('inventory.StockPicking', null=True, blank=True, on_delete=models.PROTECT,
                                related_name='moves')
    picking_type = models.ForeignKey('inventory.StockPickingType', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    # Demand as entered/scanned, in `product_uom` -- may be kg, dozen, a case, etc.
    quantity = models.DecimalField(max_digits=14, decimal_places=6)
    product_uom = models.ForeignKey('inventory.Uom', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+', verbose_name='Unit of Measure',
                                    help_text='Defaults to the product\'s storage UoM if left blank.')
    lot = models.ForeignKey('inventory.StockLot', null=True, blank=True, on_delete=models.PROTECT,
                            related_name='moves')
    # What the order asked for ("3 x Bag 25 kg"). With a packaging set, allocation reserves whole
    # sealed packages of that type first.
    packaging = models.ForeignKey('inventory.ProductPackaging', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    date = models.DateTimeField(default=timezone.now, help_text='Scheduled date: when the move should happen.')
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)

    # Required + PROTECT: a move with no source/destination is meaningless, and
    # deleting a location must never erase where stock went.
    source_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name='out_moves')
    dest_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name='in_moves')

    # -- procurement (Odoo: procure_method, group_id, rule_id, move_dest_ids, route_ids, ...) ----
    procure_method = models.CharField(max_length=20, choices=ProcureMethod.choices,
                                      default=ProcureMethod.MAKE_TO_STOCK)
    group = models.ForeignKey('inventory.ProcurementGroup', null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='moves')
    rule = models.ForeignKey('inventory.StockRule', null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='+')
    # Moves this one feeds. Inverse: move_orig_ids (moves that must finish before this one).
    move_dest_ids = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='move_orig_ids')
    routes = models.ManyToManyField('inventory.StockRoute', blank=True, related_name='+',
                                    help_text='Forced routes, carried along when this move asks for supply.')
    propagate_cancel = models.BooleanField(default=False)
    warehouse = models.ForeignKey('inventory.Warehouse', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+', help_text='Warehouse to consider for the next procurement.')
    partner = models.ForeignKey('core.Partner', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    origin = models.CharField(max_length=64, blank=True)

    origin_returned_move = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='returned_moves',
        help_text='The completed move this move returns.')

    purchase_line = models.ForeignKey(
        'purchases.PurchaseOrderLine', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='stock_moves', help_text="Source Purchase Order Line that triggered this move demand.")
    sale_line = models.ForeignKey(
        'sales.SalesOrderLine', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='stock_moves', help_text="Source Sales Order Line that triggered this move demand.")

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='stock_move_qty_positive'),
            models.CheckConstraint(condition=~Q(source_location=models.F('dest_location')),
                                   name='stock_move_src_ne_dest'),
        ]

    def __str__(self):
        uom = self.product_uom or (self.product.uom if self.product_id else None)
        return f'{self.product.name}: {self.source_location} -> {self.dest_location} ({self.quantity} {uom})'

    # ------------------------------------------------------------------ derived values
    @property
    def move_type(self):
        return self.MOVE_TYPE_BY_USAGE.get((self.source_location.usage, self.dest_location.usage))

    @property
    def quantity_in_storage_uom(self):
        """What actually gets written to StockQuant -- always the product's storage UoM.
        Unrounded: callers that compare or reserve must pass it through _round_storage()."""
        uom = self.product_uom or self.product.uom
        return uom.convert_to(self.quantity, self.product.uom)

    @property
    def warehouses(self):
        """Warehouses touched by this move."""
        from inventory.models import Warehouse
        return Warehouse.objects.filter(
            Q(pk=self.source_location.warehouse_id) | Q(pk=self.dest_location.warehouse_id))

    @property
    def _should_bypass_reservation(self):
        """Odoo: a move whose source is virtual (vendor, inventory loss...) has nothing to reserve."""
        return not self.source_location.is_stockable

    # ------------------------------------------------------------------ validation / save
    def _default_and_check_uom(self):
        if self.product_id and not self.product.is_stockable:
            raise ValidationError(f'{self.product.name} is a {self.product.get_product_type_display()}; '
                                  'it cannot appear in a stock move.')
        if self.product_id and not self.product_uom_id:
            self.product_uom_id = self.product.uom_id
        if self.product_id and self.product_uom_id and self.product_uom.category_id != self.product.uom.category_id:
            raise ValidationError(
                f'"{self.product_uom}" can\'t be used for {self.product.name}: it isn\'t the same '
                f'dimension as its storage Unit of Measure, "{self.product.uom}".')

    def save(self, *args, **kwargs):
        # Applied on every save so these are never left unset by code that skips full_clean().
        self._default_and_check_uom()
        if self.product_id and not self.company_id:
            self.company_id = self.product.company_id
        if self.picking_id and not self.picking_type_id:
            self.picking_type_id = self.picking.picking_type_id
        super().save(*args, **kwargs)
        # Odoo computes picking state/date from its moves; we refresh it when they change.
        fields = kwargs.get('update_fields')
        if self.picking_id and (fields is None or {'status', 'date', 'picking'} & set(fields)):
            self.picking._recompute()

    def clean(self):
        super().clean()
        self._default_and_check_uom()
        if self.source_location_id and self.dest_location_id:
            if self.source_location_id == self.dest_location_id:
                raise ValidationError('Source and destination must differ.')
            for loc in (self.source_location, self.dest_location):
                if loc.usage == StockLocation.Usage.VIEW:
                    raise ValidationError(f'"{loc.complete_name}" is a view location and cannot be used in a move.')

        if self.lot_id and self.product_id:
            if self.lot.product_id != self.product_id:
                raise ValidationError(f'Lot "{self.lot.name}" belongs to a different product.')
            for loc in (self.source_location, self.dest_location):
                if loc.company_id and loc.company_id != self.lot.company_id:
                    raise ValidationError(f'Lot "{self.lot.name}" belongs to another company than "{loc.complete_name}".')

        if self.packaging_id and self.product_id and self.packaging.product_id != self.product_id:
            raise ValidationError(f'Packaging "{self.packaging.name}" belongs to a different product.')

        # Tracking is enforced on the LINES (as in Odoo): a move served by several lots has no single
        # lot of its own. Only a move without lines is checked here, since complete() will then
        # create one default line mirroring it.
        has_lines = bool(self.pk and self.lines.exists())
        tracking = getattr(self.product, 'tracking', None) if self.product_id else None
        if tracking == 'none' and self.lot_id:
            raise ValidationError(f'{self.product.name} is not tracked, so it cannot be moved with a lot.')
        if not has_lines:
            if tracking in ('lot', 'serial') and not self.lot_id:
                raise ValidationError(f'{self.product.name} is tracked by {tracking}: a lot/serial number is required.')
            if tracking == 'serial' and self.product_id and self.quantity_in_storage_uom != 1:
                raise ValidationError('A serial number moves one unit at a time '
                                      f'(that\'s {self.quantity_in_storage_uom} {self.product.uom}).')

    # ------------------------------------------------------------------ state machine
    def _set_status(self, status):
        self.status = status
        self.save(update_fields=['status'])

    def _available_qty(self):
        """Storage-UoM quantity covered by lines (reserved by allocation or entered by hand)."""
        return sum((l.quantity_in_storage_uom for l in self.lines.select_related('product', 'product_uom')),
                   Decimal('0'))

    def _recompute_state(self):
        """Odoo's _recompute_state. DRAFT / COMPLETED / CANCELLED are never touched here."""
        S = self.Status
        if self.status in (S.DRAFT, S.COMPLETED, S.CANCELLED):
            return self.status
        demand = self.quantity_in_storage_uom
        available = demand if self._should_bypass_reservation else self._available_qty()
        if demand - available < self.product.uom.rounding:
            new = S.ASSIGNED
        elif available > 0:
            new = S.PARTIALLY_AVAILABLE
        elif (self.move_orig_ids.exclude(status__in=[S.COMPLETED, S.CANCELLED]).exists()
              or (self.procure_method == self.ProcureMethod.MAKE_TO_ORDER and not self.move_orig_ids.exists())):
            # waiting for a feeding move, or make-to-order whose supply (e.g. a draft PO line)
            # has not produced a move yet: reserving from the source location would steal other stock
            new = S.WAITING
        else:
            new = S.CONFIRMED
        if new != self.status:
            self._set_status(new)
        return self.status

    def confirm(self):
        StockMove.objects.filter(pk=self.pk).action_confirm()
        self.refresh_from_db()
        return self

    def assign(self, allow_break=False):
        short = StockMove.objects.filter(pk=self.pk).action_assign(allow_break=allow_break)
        self.refresh_from_db()
        return short

    # ------------------------------------------------------------------ chain / procurement
    def _prepare_procurement(self):
        """Odoo's _prepare_procurement_values: the demand this MTO move puts on its SOURCE location."""
        from inventory.models.procurement_group import Procurement
        values = {
            'group': self.group, 'route_ids': list(self.routes.all()), 'warehouse': self.warehouse,
            'partner': self.partner, 'date_planned': self.date, 'move_dest_ids': [self],
            'sale_line': self.sale_line, 'packaging': self.packaging, 'company': self.company,
        }
        return Procurement(
            product=self.product, quantity=self.quantity, uom=self.product_uom,
            location=self.source_location, name=self.rule.name if self.rule_id else '/',
            origin=self.origin or (self.picking.name if self.picking_id else '/'),
            company=self.company, values=values)

    def _push_loop(self, rule):
        """Loop guard: has `rule` already produced a move upstream of this one?"""
        if self.rule_id == rule.pk:
            return True
        frontier, seen = [self], {self.pk}
        for _ in range(10):
            frontier = list(StockMove.objects.filter(move_dest_ids__in=frontier).exclude(pk__in=seen))
            if not frontier:
                return False
            for m in frontier:
                if m.rule_id == rule.pk:
                    return True
                seen.add(m.pk)
        return False

    # ------------------------------------------------------------------ picking assignment
    def _search_picking_for_assignation(self):
        from inventory.models import ProcurementGroup, StockPicking
        if not self.group_id:
            return None
        ProcurementGroup.objects.select_for_update().get(pk=self.group_id)   # serialise per group
        return (StockPicking.objects.select_for_update()
                .filter(group_id=self.group_id, picking_type_id=self.picking_type_id,
                        source_location_id=self.source_location_id, dest_location_id=self.dest_location_id)
                .exclude(status__in=[StockPicking.Status.COMPLETED, StockPicking.Status.CANCELLED])
                .order_by('id').first())

    def _get_new_picking_values(self, moves):
        group = self.group
        origins = []
        for m in moves:
            if m.origin and m.origin not in origins:
                origins.append(m.origin)
        return dict(
            origin=', '.join(origins)[:64], picking_type=self.picking_type, company=self.company,
            partner=group.partner if group and group.partner_id else self.partner,
            group=group, move_type=group.move_type if group else 'direct',
            sales_order=group.sales_order if group else None,
            source_location=self.source_location, dest_location=self.dest_location,
            scheduled_date=min(m.date for m in moves))

    # ------------------------------------------------------------------ lines
    def _make_default_line(self):
        """One line that mirrors the move's own fields (immediate transfer)."""
        return StockMoveLine.objects.create(
            move=self, product=self.product, lot=self.lot,
            source_location=self.source_location, dest_location=self.dest_location,
            quantity=self.quantity, product_uom=self.product_uom or self.product.uom,
        )

    @transaction.atomic
    def unreserve(self, recompute=True):
        from inventory.models import StockQuant
        for line in self.lines.select_for_update().filter(reserved=True):
            StockQuant.release(line.product_id, line.source_location, line.quantity_in_storage_uom,
                               lot=line.lot, package=line.package)
            line.delete()
        if recompute:
            self._recompute_state()

    def _round_storage(self, qty):
        r = self.product.uom.rounding  # e.g. Decimal('0.001')
        return (qty / r).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * r

    # Tolerance (storage-UoM units) for "this conversion round-trips exactly". Absorbs the error
    # of stored UoM factors, but not a real mismatch.
    SPLIT_EXACT_TOLERANCE = Decimal('0.0001')

    def _split(self, qty_storage):
        """Take `qty_storage` (storage UoM) off this move's demand and return a new move for it
        (Odoo: stock.move._split). The remainder keeps its place in the chain and its
        sale/purchase line. No lines, so nothing reserved.

        UoM handling:
          * If the shortage is a whole number of steps of the move's UoM, both moves keep that UoM.
          * Otherwise (e.g. 18 Units of a Case-based move) the completed move is converted to the
            storage UoM for the quantity that actually moved, and the backorder is created in the
            storage UoM. Nothing is rounded away, so quants, valuation and invoicing agree.
            The caller MUST persist product_uom as well as quantity (complete() does).

        Returns None only if there is nothing to split (qty_storage <= 0)."""
        storage_uom = self.product.uom
        move_uom = self.product_uom or storage_uom

        qty_storage = self._round_storage(qty_storage)
        if qty_storage <= 0:
            return None

        # Try to express the shortage in the move's own UoM. Snap factor dust first (12 Units =
        # 0.99999996 Dozen must count as 1), then round DOWN so demand is never inflated.
        qty_in_move_uom = storage_uom.convert_to(qty_storage, move_uom)
        qty_in_move_uom = qty_in_move_uom.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
        r = move_uom.rounding
        qty_rounded = (qty_in_move_uom / r).quantize(Decimal('1'), rounding=ROUND_DOWN) * r

        exact = (
            qty_rounded > 0
            and qty_rounded < self.quantity
            and abs(move_uom.convert_to(qty_rounded, storage_uom) - qty_storage)
                <= self.SPLIT_EXACT_TOLERANCE
        )

        if exact:
            new_qty, new_uom = qty_rounded, move_uom
            self.quantity = self.quantity - new_qty
        else:
            # Lossless fallback: both moves in storage UoM.
            done_storage = self._round_storage(self.quantity_in_storage_uom) - qty_storage
            if done_storage <= 0:
                return None  # complete() already guards this; defensive
            new_qty, new_uom = qty_storage, storage_uom
            self.product_uom = storage_uom
            self.quantity = done_storage

        new = StockMove.objects.create(
            product=self.product, company=self.company, picking=self.picking, picking_type=self.picking_type,
            quantity=new_qty, product_uom=new_uom, lot=self.lot, packaging=self.packaging,
            status=self.Status.CONFIRMED, date=self.date, origin_returned_move=self.origin_returned_move,
            source_location=self.source_location, dest_location=self.dest_location,
            procure_method=self.procure_method, group=self.group, rule=self.rule, origin=self.origin,
            propagate_cancel=self.propagate_cancel, warehouse=self.warehouse, partner=self.partner,
            sale_line=self.sale_line, purchase_line=self.purchase_line)
        new.move_dest_ids.set(self.move_dest_ids.all())
        new.move_orig_ids.set(self.move_orig_ids.all())
        new.routes.set(self.routes.all())
        new._recompute_state()
        return new

    # ------------------------------------------------------------------ done
    @transaction.atomic
    def complete(self, allow_partial=True):
        """Odoo's _action_done: move the stock line by line, then mark the move done.

          * no lines            -> one default line for the full demand (immediate transfer);
          * lines == demand     -> the move completes;
          * lines <  demand     -> completes for the lines' total, the rest is split off as a new
                                   move which is returned so the picking can backorder it;
          * lines >  demand     -> error (no over-delivery).
        A DRAFT move is confirmed first; a WAITING move cannot be completed.
        Afterwards the moves this one feeds are recomputed and reserved. Returns the remainder or None."""
        from inventory.models import StockQuant
        S = self.Status
        move = StockMove.objects.select_for_update().get(pk=self.pk)
        if move.status == S.DRAFT:
            StockMove.objects.filter(pk=move.pk).action_confirm()
            move = StockMove.objects.select_for_update().get(pk=self.pk)
        if move.status in (S.COMPLETED, S.CANCELLED):
            raise ValidationError(f'Only open moves can be completed (this one is {move.status}).')
        if move.status == S.WAITING:
            raise ValidationError('This move is waiting for another operation to finish first.')
        move.clean()

        lines = list(move.lines.select_related('product', 'lot', 'source_location', 'dest_location', 'product_uom',
                                               'package', 'result_package'))
        if not lines:
            lines = [move._make_default_line()]
        for line in lines:
            line.clean()

        demand = move._round_storage(move.quantity_in_storage_uom)
        done = move._round_storage(sum(l.quantity_in_storage_uom for l in lines))
        # UoM conversion can leave dust (24.99999999 vs 25); anything under one rounding step is "equal".
        rounding = move.product.uom.rounding
        short = demand - done
        if short <= -rounding:
            raise ValidationError(f'Lines total {done} but the move only demands {demand}.')
        if short < rounding:
            short = Decimal('0')
        if short > 0 and not allow_partial:
            raise ValidationError(f'Lines total {done} but the move demands {demand}.')

        # Guard: if nothing beyond one rounding step actually moved, refuse. Splitting
        # here would hand the WHOLE demand to the backorder and save this move with
        # quantity = 0, which the quantity>0 check constraint rejects -> IntegrityError
        # deep inside picking validation.
        if short >= demand:
            raise ValidationError(
                f'Only {done} {move.product.uom} of {demand} was moved, which is below one '
                f'rounding step; there is nothing meaningful to complete.')

        steps = []
        for line in lines:
            for loc in (line.source_location, line.dest_location):
                if not loc.active:
                    raise ValidationError(f'"{loc.complete_name}" is archived.')
            qty = move._round_storage(line.quantity_in_storage_uom)
            steps.append((line.source_location, -qty, line, line.package, True))
            steps.append((line.dest_location, qty, line, line.result_package, False))

        # Fixed lock order (by location pk) across ALL lines so opposite transfers cannot deadlock.
        for loc, delta, line, pkg, is_source in sorted(steps, key=lambda s: s[0].pk):
            if loc.is_stockable:           # virtual locations keep no quants
                StockQuant.apply(line.product_id, loc, delta, lot=line.lot, package=pkg)
                if is_source and line.reserved:
                    StockQuant.release(line.product_id, loc, -delta, lot=line.lot, package=pkg)
        move.lines.filter(reserved=True).update(reserved=False)

        # Steps interleave by location, so a moved package can only be checked once all steps are in.
        for pkg in {l.result_package for l in lines if l.result_package_id}:
            pkg.assert_single_location()

        for line in lines:
            if line.lot_id and getattr(line.product, 'tracking', None) == 'serial' and line.lot.on_hand > 1:
                raise ValidationError(f'Serial number "{line.lot.name}" would exist more than once in stock.')

        # _split shrinks move.quantity to what moved and may switch move.product_uom to the
        # storage UoM, so BOTH are saved below.
        remainder = move._split(short) if short > 0 else None
        if short > 0 and remainder is None:
            # Never let a shortage disappear: raising rolls back the quant changes above.
            raise ValidationError(
                f'Could not split the {short} {move.product.uom} shortage of {move.product.name} '
                f'into a backorder.')
        move.status, move.completed_at = S.COMPLETED, timezone.now()
        move.save(update_fields=['status', 'completed_at', 'quantity', 'product_uom'])
        self.status, self.completed_at = move.status, move.completed_at
        self.quantity, self.product_uom = move.quantity, move.product_uom

        # Odoo: the moves fed by this one stop waiting and try to reserve what arrived.
        dests = list(move.move_dest_ids.exclude(status__in=[S.DRAFT, S.COMPLETED, S.CANCELLED]))
        for d in dests:
            d._recompute_state()
        StockMove.objects.filter(pk__in=[d.pk for d in dests]).action_assign()
        return remainder

    # ------------------------------------------------------------------ cancel
    @transaction.atomic
    def cancel(self):
        """Odoo's _action_cancel, including propagation along the chain:
          * propagate_cancel: cancel the next move once ALL its feeding moves are cancelled;
          * otherwise, once all siblings are done/cancelled the next move stops being MTO and
            no longer waits for this one."""
        S = self.Status
        if self.status == S.COMPLETED:
            raise ValidationError('Can not cancel a completed stock move; create a reverse move instead.')
        if self.status == S.CANCELLED:
            return
        self.unreserve(recompute=False)
        self._set_status(S.CANCELLED)

        for dest in list(self.move_dest_ids.exclude(status__in=[S.COMPLETED, S.CANCELLED])):
            siblings = dest.move_orig_ids.exclude(pk=self.pk)
            if self.propagate_cancel:
                if not siblings.exclude(status=S.CANCELLED).exists():
                    dest.cancel()
            elif not siblings.exclude(status__in=[S.COMPLETED, S.CANCELLED]).exists():
                dest.procure_method = self.ProcureMethod.MAKE_TO_STOCK
                dest.save(update_fields=['procure_method'])
                dest.move_orig_ids.remove(self)
                dest._recompute_state()


class StockMoveLine(models.Model):
    """How a StockMove was actually fulfilled (Odoo: stock.move.line).
    StockMove = demand ("deliver 10"); StockMoveLine = execution ("6 from lot X, 4 from lot Y").
    Quantity is in `product_uom`, like the move; stock is written in the storage UoM."""

    move = models.ForeignKey(StockMove, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='+')
    lot = models.ForeignKey('inventory.StockLot', null=True, blank=True, on_delete=models.PROTECT,
                            related_name='move_lines')
    source_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name='out_move_lines')
    dest_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name='in_move_lines')
    quantity = models.DecimalField(max_digits=14, decimal_places=6)
    product_uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, related_name='+')
    # package (source) / result_package (destination). Same package on both = it moved intact;
    # source only = taken out of the package; result only = put into a package (e.g. receiving a bag).
    package = models.ForeignKey('inventory.StockQuantPackage', null=True, blank=True,
                                on_delete=models.PROTECT, related_name='+')
    result_package = models.ForeignKey('inventory.StockQuantPackage', null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+')
    reserved = models.BooleanField(default=False, help_text='Created by action_assign; holds quant reservation.')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='stock_move_line_qty_positive'),
            models.CheckConstraint(condition=~Q(source_location=models.F('dest_location')),
                                   name='stock_move_line_src_ne_dest'),
        ]

    def __str__(self):
        lot = f' [{self.lot.name}]' if self.lot_id else ''
        return f'{self.product.name}{lot}: {self.source_location} -> {self.dest_location} ({self.quantity} {self.product_uom})'

    @property
    def quantity_in_storage_uom(self):
        return self.product_uom.convert_to(self.quantity, self.product.uom)

    def save(self, *args, **kwargs):
        # Inherit from the move so lines can be created with just move + quantity.
        if self.move_id:
            self.product_id = self.product_id or self.move.product_id
            self.source_location_id = self.source_location_id or self.move.source_location_id
            self.dest_location_id = self.dest_location_id or self.move.dest_location_id
        if self.product_id and not self.product_uom_id:
            self.product_uom_id = self.product.uom_id
        super().save(*args, **kwargs)
        # what is covered by lines decides the move state (partially available / available)
        StockMove.objects.get(pk=self.move_id)._recompute_state()

    def delete(self, *args, **kwargs):
        move_id = self.move_id
        result = super().delete(*args, **kwargs)
        StockMove.objects.get(pk=move_id)._recompute_state()
        return result

    def clean(self):
        super().clean()
        S = StockMove.Status
        if self.move.status in (S.COMPLETED, S.CANCELLED):
            raise ValidationError('Lines can only be changed while the move is open.')
        if self.product_id != self.move.product_id:
            raise ValidationError('A line must be for the same product as its move.')
        if self.product_uom.category_id != self.product.uom.category_id:
            raise ValidationError(f'"{self.product_uom}" is not the same dimension as '
                                  f'{self.product.name}\'s storage Unit of Measure.')
        if self.source_location_id == self.dest_location_id:
            raise ValidationError('Source and destination must differ.')
        for loc in (self.source_location, self.dest_location):
            if loc.usage == StockLocation.Usage.VIEW:
                raise ValidationError(f'"{loc.complete_name}" is a view location and cannot be used in a move.')

        if self.lot_id:
            if self.lot.product_id != self.product_id:
                raise ValidationError(f'Lot "{self.lot.name}" belongs to a different product.')
            for loc in (self.source_location, self.dest_location):
                if loc.company_id and loc.company_id != self.lot.company_id:
                    raise ValidationError(f'Lot "{self.lot.name}" belongs to another company than "{loc.complete_name}".')

        tracking = getattr(self.product, 'tracking', None)
        if tracking in ('lot', 'serial') and not self.lot_id:
            raise ValidationError(f'{self.product.name} is tracked by {tracking}: a lot/serial number is required.')
        if tracking == 'none' and self.lot_id:
            raise ValidationError(f'{self.product.name} is not tracked, so it cannot be moved with a lot.')
        if tracking == 'serial' and self.quantity_in_storage_uom != 1:
            raise ValidationError('A serial number moves one unit at a time.')
        if self.package_id and not self.source_location.is_stockable:
            raise ValidationError('A source package must sit in a stockable location.')
        if self.result_package_id and not self.dest_location.is_stockable:
            raise ValidationError(f'Package "{self.result_package}" cannot be put in "{self.dest_location.complete_name}".')