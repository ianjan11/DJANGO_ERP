from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from inventory.models import StockMove

class StockPickingType(models.Model):
    """A kind of transfer for one warehouse (Odoo: stock.picking.type).
    Controls default locations and how pickings of this kind are named."""
    class Code(models.TextChoices):
        INCOMING = 'incoming', 'Receipts'
        OUTGOING = 'outgoing', 'Delivery Orders'
        INTERNAL = 'internal', 'Internal Transfers'
        RETURN = 'return', 'Returns'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    name = models.CharField(max_length=64)
    code = models.CharField(max_length=10, choices=Code.choices)
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.CASCADE, related_name='picking_types')
    default_source_location = models.ForeignKey('inventory.StockLocation', null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name='+')
    default_dest_location = models.ForeignKey('inventory.StockLocation', null=True, blank=True,
                                               on_delete=models.PROTECT, related_name='+')
    # Where a return of a picking of this type should go, e.g. Delivery Orders -> Receipts,
    # Receipts -> a dedicated Vendor Returns type. Nullable: not every type is returnable.
    return_picking_type = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                            related_name='+')
    sequence_prefix = models.CharField(max_length=20, help_text="e.g. 'WH/OUT/'")
    last_sequence_number = models.PositiveIntegerField(default=0, editable=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['warehouse_id', 'code']
        constraints = [
            models.UniqueConstraint(fields=['warehouse', 'name'], name='picking_type_warehouse_name_uniq'),
        ]

    def __str__(self):
        return f'{self.warehouse.code}: {self.name}'

    @transaction.atomic
    def next_name(self):
        """Atomically reserve and format the next sequence number, e.g. 'WH/OUT/00001'."""
        updated = StockPickingType.objects.filter(pk=self.pk).update(
            last_sequence_number=models.F('last_sequence_number') + 1)
        self.refresh_from_db(fields=['last_sequence_number'])
        return f'{self.sequence_prefix}{self.last_sequence_number:05d}'

class StockPicking(models.Model):
    """One transfer: a batch of StockMoves reserved, validated and (if only partly fulfilled)
    backordered together (Odoo: stock.picking). Like Odoo, its status and scheduled date are
    derived from its moves (see _recompute) and its moves are grouped by ProcurementGroup."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        WAITING = 'WAITING', 'Waiting Another Operation'
        CONFIRMED = 'CONFIRMED', 'Waiting'
        ASSIGNED = 'ASSIGNED', 'Ready'
        COMPLETED = 'COMPLETED', 'Done'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class MoveType(models.TextChoices):
        DIRECT = 'direct', 'As soon as possible'
        ONE = 'one', 'When all products are ready'

    name = models.CharField(max_length=50, blank=True, editable=False)
    picking_type = models.ForeignKey(StockPickingType, on_delete=models.PROTECT, related_name='pickings')

    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT, related_name='pickings', editable=False)
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='pickings', editable=False)
    partner = models.ForeignKey('core.Partner', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    # Pickings of one demand (every step of a sales order, one reordering run...) share a group.
    group = models.ForeignKey('inventory.ProcurementGroup', null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='pickings')
    # direct: ready as soon as one move is; one: ready only when all moves are (Odoo: move_type).
    move_type = models.CharField(max_length=10, choices=MoveType.choices, default=MoveType.DIRECT)

    sales_order = models.ForeignKey(
        'sales.SalesOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='pickings',
        help_text="Originating Sales Order for outgoing delivery transfers.")
    purchase_order = models.ForeignKey(
        'purchases.PurchaseOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='pickings',
        help_text="Originating Purchase Order for incoming receipts.")

    account_move = models.ForeignKey(
        'accounting.AccountMove', null=True, blank=True, on_delete=models.SET_NULL, related_name='pickings',
        help_text="Account move for this Picking.")

    source_location = models.ForeignKey('inventory.StockLocation', on_delete=models.PROTECT, related_name='+')
    dest_location = models.ForeignKey('inventory.StockLocation', on_delete=models.PROTECT, related_name='+')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    backorder_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='backorders')
    # Free-text pointer to whatever triggered this transfer (a sales order ref, a PO ref...).
    origin = models.CharField(max_length=64, blank=True)
    reason = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. 'Annual Audit Discrepancy', 'Damaged in transit', 'Routine Rebalancing'")
    note = models.TextField(blank=True, help_text="Internal notes or memo")

    scheduled_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    date_done = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f'{self.picking_type} (draft)'

    def save(self, *args, **kwargs):
        if not self.warehouse_id:
            self.warehouse_id = self.picking_type.warehouse_id
        if not self.source_location_id:
            self.source_location_id = self.picking_type.default_source_location_id
        if not self.dest_location_id:
            self.dest_location_id = self.picking_type.default_dest_location_id
        if not self.company_id:
            self.company_id = self.picking_type.warehouse.company_id
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating and not self.name:
            self.name = self.picking_type.next_name()
            StockPicking.objects.filter(pk=self.pk).update(name=self.name)

    @property
    def has_backorder(self):
        return self.backorders.exclude(status__in=[self.Status.COMPLETED, self.Status.CANCELLED]).exists()

    # ------------------------------------------------------------------ derived status / date
    @staticmethod
    def _relevant_move_status(moves, move_type):
        """Odoo's _get_relevant_state_among_moves: which move status stands for the whole picking.
        direct: ASSIGNED as soon as any move is (at least partly) available;
        one:    as ready as the LEAST ready move."""
        S = StockMove.Status
        rank = {S.ASSIGNED: 4, S.WAITING: 3, S.PARTIALLY_AVAILABLE: 2, S.CONFIRMED: 1}
        todo = sorted((m for m in moves if m.status not in (S.COMPLETED, S.CANCELLED)),
                      key=lambda m: (rank.get(m.status, 0), m.quantity))
        if not todo:
            return S.ASSIGNED
        if move_type == StockPicking.MoveType.ONE:
            least = todo[0].status
            return S.CONFIRMED if least == S.PARTIALLY_AVAILABLE else least
        if todo[0].status != S.ASSIGNED and any(m.status in (S.ASSIGNED, S.PARTIALLY_AVAILABLE) for m in todo):
            return S.ASSIGNED
        return todo[-1].status

    def _recompute(self):
        """Refresh status and scheduled date from the moves (Odoo computes these as stored fields)."""
        S, P = StockMove.Status, self.Status
        moves = list(self.moves.all())
        if not moves or any(m.status == S.DRAFT for m in moves):
            new = P.DRAFT
        elif all(m.status == S.CANCELLED for m in moves):
            new = P.CANCELLED
        elif all(m.status in (S.COMPLETED, S.CANCELLED) for m in moves):
            new = P.COMPLETED
        else:
            new = P(self._relevant_move_status(moves, self.move_type))   # WAITING / CONFIRMED / ASSIGNED

        changed = []
        if new != self.status:
            self.status = new
            changed.append('status')
        dates = [m.date for m in moves if m.status not in (S.COMPLETED, S.CANCELLED)]
        if dates:
            sched = max(dates) if self.move_type == self.MoveType.ONE else min(dates)
            if sched != self.scheduled_date:
                self.scheduled_date = sched
                changed.append('scheduled_date')
        if changed:
            self.save(update_fields=changed)
        return self.status

    # ------------------------------------------------------------------ actions (Odoo names in brackets)
    @transaction.atomic
    def action_confirm(self):
        """[action_confirm] Confirm the draft moves."""
        StockMove.objects.filter(picking=self, status=StockMove.Status.DRAFT).action_confirm()
        self.refresh_from_db()
        return self

    @transaction.atomic
    def action_assign(self, allow_break=False):
        """[action_assign] Reserve stock for the moves. Returns {move: shortage}."""
        self.action_confirm()
        return StockMove.objects.filter(picking=self).action_assign(allow_break=allow_break)

    @transaction.atomic
    def cancel(self):
        """[action_cancel]"""
        if self.status == self.Status.COMPLETED:
            raise ValidationError(f'"{self}" is already completed; it cannot be cancelled.')
        for move in self.moves.exclude(status__in=[StockMove.Status.COMPLETED, StockMove.Status.CANCELLED]):
            move.cancel()
        self.refresh_from_db()
        self._recompute()

    @transaction.atomic
    def validate(self, create_backorder=True, user=None):
        """[button_validate] Complete every move that is not waiting, for what its lines actually moved.
        Moves still waiting for another operation and the remainders of partly fulfilled moves go on a
        new backorder picking (create_backorder=True) or are cancelled ("no backorder"; a waiting move
        cannot be dropped silently, so that case is refused). Real errors (archived location, bad
        lines...) propagate. Returns the backorder, or None if nothing was left over."""
        S = StockMove.Status
        picking = StockPicking.objects.select_for_update().get(pk=self.pk)
        if picking.status in (self.Status.COMPLETED, self.Status.CANCELLED):
            raise ValidationError(f'This picking is {picking.status}; it cannot be validated.')
        if picking.status == self.Status.DRAFT:
            picking.action_confirm()

        open_moves = picking.moves.select_for_update().exclude(status__in=[S.COMPLETED, S.CANCELLED])
        moves = list(open_moves.exclude(status=S.WAITING))
        waiting = list(open_moves.filter(status=S.WAITING))
        if not moves:
            raise ValidationError(f'"{picking}" has no moves ready to validate.')
        if waiting and not create_backorder:
            raise ValidationError(f'"{picking}" has moves waiting for another operation; '
                                  'validate with a backorder instead.')

        remainders = [r for r in (m.complete() for m in moves) if r] + waiting

        backorder = None
        if remainders and create_backorder:
            backorder = StockPicking.objects.create(
                picking_type=picking.picking_type, company=picking.company, partner=picking.partner,
                source_location=picking.source_location, dest_location=picking.dest_location,
                backorder_of=picking, origin=picking.origin, scheduled_date=picking.scheduled_date,
                sales_order=picking.sales_order, purchase_order=picking.purchase_order,
                group=picking.group, move_type=picking.move_type,
            )
            StockMove.objects.filter(pk__in=[r.pk for r in remainders]).update(picking=backorder)
            backorder._recompute()
        else:
            for r in remainders:
                r.cancel()

        picking.refresh_from_db()
        picking.date_done = timezone.now()
        picking.save(update_fields=['date_done'])
        picking._recompute()                       # all moves done/cancelled -> COMPLETED

        if picking.status == self.Status.COMPLETED:
            picking._post_valuation(user)

        self.status, self.date_done = picking.status, picking.date_done
        self.account_move_id = picking.account_move_id  # keep caller's instance in sync
        return backorder


    def _return_kind(self, direction):
        """
        Returns are recognised by what the moves reference, not by picking type:
          * an INCOMING move tied to a sale line     -> customer (sales) return
          * an OUTGOING move tied to a purchase line -> supplier (purchase) return
        Anything else is a normal receipt / delivery / direct adjustment.
        """
        moves = self.moves.filter(status=StockMove.Status.COMPLETED)
        has_sale = moves.filter(sale_line__isnull=False).exists()
        has_purchase = moves.filter(purchase_line__isnull=False).exists()

        if has_sale and has_purchase:
            raise ValidationError(
                f'"{self}" mixes sale-line and purchase-line moves; split it before validating.')

        if direction == 'in':
            return 'sales' if has_sale else None
        return 'purchase' if has_purchase else None

    def _post_valuation(self, user):
        """
        Post financial valuation for pickings crossing the company boundary:

            receipt          -> GRNI   create_valuation_for_incoming_picking
            delivery         -> GDNI   create_valuation_for_picking
            customer return  -> create_valuation_for_sales_return
            supplier return  -> create_valuation_for_purchase_return

        Returns have their own valuation and must never go through the receipt
        or delivery functions.
        """
        from accounting.services.account_move_services.vendor.purchase_grni_account_move import (
            create_valuation_for_incoming_picking)
        from accounting.services.account_move_services.customer.sales_gdni_account_move import (
            create_valuation_for_picking)
        from accounting.services.account_move_services.returns_valuation import (
            create_valuation_for_sales_return, create_valuation_for_purchase_return)
        from inventory.models import StockLocation

        # Guard: Ensure locations exist
        if not self.source_location or not self.dest_location:
            return None

        internal = StockLocation.Usage.INTERNAL
        src, dst = self.source_location.usage, self.dest_location.usage

        # Guard: Strictly ignore internal warehouse transfers
        if src == internal and dst == internal:
            return None

        picking_code = getattr(self.picking_type, 'code', None)

        # 1. Goods coming in: vendor receipt, or customer return
        if dst == internal and src != internal:
            if picking_code and picking_code not in ['incoming', 'return']:
                return None
            if self._return_kind('in') == 'sales':
                return create_valuation_for_sales_return(self, user)
            return create_valuation_for_incoming_picking(self, user)

        # 2. Goods going out: customer delivery, or return to supplier
        if src == internal and dst != internal:
            if picking_code and picking_code not in ['outgoing', 'return']:
                return None
            if self._return_kind('out') == 'purchase':
                return create_valuation_for_purchase_return(self, user)
            return create_valuation_for_picking(self, user)

        return None

    # ------------------------------------------------------------------ chain navigation
    def next_pickings(self):
        """Open pickings fed by this one (pick -> pack -> ship). Usually one."""
        return (StockPicking.objects
                .filter(moves__move_orig_ids__picking=self)
                .exclude(pk=self.pk)
                .exclude(status=self.Status.CANCELLED)
                .distinct()
                .order_by('id'))

    def previous_pickings(self):
        """Pickings that feed this one."""
        return (StockPicking.objects
                .filter(moves__move_dest_ids__picking=self)
                .exclude(pk=self.pk)
                .exclude(status=self.Status.CANCELLED)
                .distinct()
                .order_by('id'))