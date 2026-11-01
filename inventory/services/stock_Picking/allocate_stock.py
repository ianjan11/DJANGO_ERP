"""
Allocate (reserve) stock for a StockMove by creating reserved StockMoveLines
(Odoo: stock.move._action_assign). This is the ONLY allocation engine.

Principles (same as StockQuant / StockQuantPackage / StockMoveLine):
  * Reservations live on StockQuant.reserved_quantity; free = quantity - reserved_quantity.
    Every reserved line names the exact quant it holds (location, lot, package).
  * Demand is converted to the product's storage UoM first; quants only ever hold that UoM.
  * move.packaging set  -> whole, sealed, fully-free packages of that type come first.
    Loose stock / opened packages are used only if allow_break=True, so a bag order can never
    be filled with loose kilos.
  * no move.packaging   -> loose stock first, then packages (taking part of a package opens it).
  * Planning is separate from writing, so allow_partial=False raises before anything is created.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from inventory.models import StockLocation, StockMove, StockQuant
from inventory.models.stock_move import StockMoveLine

ZERO = Decimal('0')
RS = StockLocation.RemovalStrategy


@dataclass
class AllocationResult:
    lines: list = field(default_factory=list)
    shortage: Decimal = ZERO          # in the product's storage UoM
    broke_package: bool = False       # True if stock was taken out of a package (it is now open)

    @property
    def is_complete(self):
        return self.shortage <= 0


# --------------------------------------------------------------------------- #
# Removal strategy
# --------------------------------------------------------------------------- #
def resolve_removal_strategy(location):
    """Location's own strategy, else nearest ancestor's, else FIFO."""
    if location.removal_strategy:
        return location.removal_strategy
    for ancestor in sorted(location.ancestors(), key=lambda l: len(l.parent_path), reverse=True):
        if ancestor.removal_strategy:
            return ancestor.removal_strategy
    return RS.FIFO


def _age_key(q):
    """Oldest first; quants without in_date sort last, by pk."""
    return (0, q.in_date, q.pk) if q.in_date else (1, None, q.pk)


def _expiry(q):
    return q.lot.expiration_date if q.lot_id else None


def _sort_units(units, strategy):
    """Sort 'units' -- each a list of quants: one loose quant, or every quant of one package."""
    if strategy == RS.LIFO:
        return sorted(units, key=lambda u: max(_age_key(q) for q in u), reverse=True)
    if strategy == RS.CLOSEST:
        return sorted(units, key=lambda u: (u[0].location.complete_name, u[0].pk))
    if strategy == RS.FEFO:
        def key(u):
            expiries = [e for e in map(_expiry, u) if e]
            age = min(_age_key(q) for q in u)
            return (0, min(expiries), age) if expiries else (1, None, age)   # no expiry -> last
        return sorted(units, key=key)
    return sorted(units, key=lambda u: min(_age_key(q) for q in u))          # FIFO


# --------------------------------------------------------------------------- #
# Planning (pure: no writes, so it can be unit-tested without a database)
# --------------------------------------------------------------------------- #
def build_plan(*, rows, candidate_ids, demand, tracking, strategy,
               product_id, packaging_id=None, packaging_qty=None, allow_break=False):
    """
    rows          -- locked quants: every candidate plus every quant of any package a candidate is in.
    candidate_ids -- pks of rows that match product / location / company / lot rules.
    Returns (plan, remaining, broke_package); plan = [(quant, amount, keep_package)].
    """
    def free(q):
        return q.quantity - q.reserved_quantity

    by_pkg = defaultdict(list)
    for q in rows:
        if q.package_id:
            by_pkg[q.package_id].append(q)
    candidates = [q for q in rows if q.pk in candidate_ids and free(q) > 0]
    cand_set = {q.pk for q in candidates}

    taken = defaultdict(lambda: ZERO)
    plan, remaining, broke = [], demand, False

    # Phase 1: whole sealed packages of the requested type.
    if packaging_id and tracking != 'serial':
        units = []
        for quants in by_pkg.values():
            if quants[0].package.packaging_id != packaging_id:
                continue
            if (all(q.product_id == product_id and q.pk in cand_set and q.reserved_quantity == 0
                    for q in quants)
                    and len({q.location_id for q in quants}) == 1
                    and sum(q.quantity for q in quants) == packaging_qty):    # sealed = full size
                units.append(quants)
        for unit in _sort_units(units, strategy):
            if remaining < packaging_qty:
                break
            for q in unit:
                plan.append((q, q.quantity, True))
                taken[q.pk] += q.quantity
            remaining -= packaging_qty

    # Phase 2: loose stock, then (breaking) packages. Skipped for packaged demand unless allowed.
    if remaining > 0 and (allow_break or not packaging_id):
        for loose in (True, False):
            group = [[q] for q in candidates
                     if (q.package_id is None) == loose and free(q) - taken[q.pk] > 0]
            for (q,) in _sort_units(group, strategy):
                if remaining <= 0:
                    break
                available = free(q) - taken[q.pk]
                if tracking == 'serial':
                    if available < 1:
                        continue
                    amount = Decimal('1')                   # one line per serial number
                else:
                    amount = min(available, remaining)
                # The package travels with the stock only if this empties its single quant.
                whole = bool(q.package_id and amount == q.quantity and len(by_pkg[q.package_id]) == 1)
                broke = broke or bool(q.package_id and not whole)
                plan.append((q, amount, whole))
                taken[q.pk] += amount
                remaining -= amount

    return plan, max(remaining, ZERO), broke


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
@transaction.atomic
def allocate_stock_move(stock_move, *, allow_partial=True, allow_break=False, reset=True):
    """
    allow_partial -- False: raise (creating nothing) if demand can't be fully covered.
    allow_break   -- with move.packaging set, also allow loose stock / opened packages.
    reset         -- True: release this move's existing reservation first, so calling twice
                     doesn't double-allocate.
    """
    move = (StockMove.objects.select_for_update(of=('self',))
            .select_related('product__uom', 'product_uom', 'source_location', 'dest_location',
                            'lot', 'picking', 'packaging')
            .get(pk=stock_move.pk))


    product, source = move.product, move.source_location

    # Virtual sources (vendors, inventory loss...) keep no quants; complete()
    # creates the default line for those.
    if not source.is_stockable:
        return AllocationResult()

    if reset:
        move.unreserve()                       # gives the quants their reservation back
    if move.lines.exists():
        raise ValidationError('This move already has lines; unreserve it first.')

    tracking = getattr(product, 'tracking', 'none') or 'none'
    demand = move._round_storage(move.quantity_in_storage_uom)      # NOT move.quantity: that may be in kg, a dozen, ...

    if tracking == 'serial' and demand != demand.to_integral_value():
        raise ValidationError(f'{product.name} is serial-tracked: quantity must be a whole number '
                              f'(that\'s {demand} {product.uom}).')

    # Source location + everything below it (never ancestors), usable ones only.
    locations = list(source.descendants(include_self=True)
                     .filter(active=True, usage__in=StockLocation.STOCKABLE_USAGES))
    if not locations:
        return _finish(move, [], demand, allow_partial)

    base = (StockQuant.objects
            .filter(product_id=product.pk, location__in=locations, quantity__gt=0)
            .exclude(location_id=move.dest_location_id))      # a line must not start where it ends
    company_id = move.picking.company_id if move.picking_id else source.company_id
    if company_id:
        base = base.filter(company_id=company_id)
    # Tracking (mirrors StockMove.clean / StockMoveLine.clean)
    if tracking == 'none':
        base = base.filter(lot__isnull=True)
    else:
        base = base.filter(lot__isnull=False)
        if move.lot_id:
            base = base.filter(lot_id=move.lot_id)

    # Lock candidates AND every quant of the packages they sit in (sealed check needs them all),
    # in one query ordered by pk so concurrent allocators lock in the same order.
    cand = list(base.values_list('pk', 'package_id'))
    candidate_ids = {pk for pk, _p in cand}
    package_ids = {p for _pk, p in cand if p}
    rows = list(StockQuant.objects.select_for_update(of=('self',))
                .select_related('location', 'lot', 'package')
                .filter(Q(pk__in=candidate_ids) | Q(package_id__in=package_ids))
                .exclude(quantity=0).order_by('id'))

    plan, shortage, broke = build_plan(
        rows=rows, candidate_ids=candidate_ids, demand=demand, tracking=tracking,
        strategy=resolve_removal_strategy(source), product_id=product.pk,
        packaging_id=move.packaging_id, packaging_qty=move.packaging.qty if move.packaging_id else None,
        allow_break=allow_break)
    return _finish(move, plan, shortage, allow_partial, broke)


def _finish(move, plan, shortage, allow_partial, broke_package=False):
    if shortage > 0 and not allow_partial:
        raise ValidationError(
            f'Not enough stock for {move.product.name} in "{move.source_location.complete_name}": '
            f'short by {shortage} {move.product.uom}.')

    dest_stockable = move.dest_location.is_stockable
    lines = []
    for quant, amount, keep_package in plan:
        quant.reserved_quantity += amount                      # quant is locked by the caller
        quant.save(update_fields=['reserved_quantity'])
        lines.append(StockMoveLine.objects.create(
            move=move, product=move.product, lot=quant.lot, package=quant.package,
            result_package=quant.package if keep_package and dest_stockable else None,
            source_location=quant.location,        # actual child location the stock is in
            dest_location=move.dest_location,
            quantity=amount, product_uom=move.product.uom,     # storage UoM -> totals match exactly
            reserved=True))
    return AllocationResult(lines=lines, shortage=shortage, broke_package=broke_package)