from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from inventory.models import (
    StockLocation, StockMove, StockMoveLine, StockPicking, StockPickingType, StockQuant,
)
from inventory.services.adjustments_and_transfers.inventory_adjustment_service import inventory_adjustment_service


def _adjustment_location(company):
    """The virtual 'Inventory adjustment' location (usage=INVENTORY, not Scrap).
    bootstrap_default_locations() creates it with company=None, so accept both;
    a company-specific one wins over the shared one."""
    loc = (StockLocation.objects
           .filter(usage=StockLocation.Usage.INVENTORY, scrap_location=False, active=True)
           .filter(Q(company=company) | Q(company__isnull=True))
           .order_by(models.F('company_id').desc(nulls_last=True), 'id')
           .first())
    if not loc:
        raise ValidationError("Virtual 'Inventory adjustment' location is missing. "
                              "Run bootstrap_default_locations().")
    return loc


def _adjustment_picking_type(warehouse, adj_location):
    """One ADJUSTMENT type per warehouse, created lazily.
    Add a unique constraint on (warehouse, code) so get_or_create can never hit duplicates."""
    T = StockPickingType
    picking_type, _ = T.objects.get_or_create(
        warehouse=warehouse, code=T.Code.ADJUSTMENT,
        defaults={
            'name': f'{warehouse.code}: Inventory Adjustments',
            'sequence_prefix': f'{warehouse.code}/ADJ/',
            'default_source_location': adj_location,
            'default_dest_location': warehouse.lot_stock,
        })
    return picking_type


@transaction.atomic
def adjust_stock(*, quant: StockQuant, counted_quantity: Decimal, user=None, reason: str = None,
                 expected_quantity: Decimal = None):
    """
    Set a quant's on-hand to the physically counted quantity.

    expected_quantity: what the counter saw on screen. If given and the locked quant no longer
    matches, the count is rejected as stale instead of applying a wrong correction.

    Returns the validated StockPicking, or None if the count matches.
    """
    if not quant:
        raise ValidationError("Target stock record (quant) not found.")

    counted_qty = Decimal(str(counted_quantity))
    if counted_qty < 0:
        raise ValidationError("Counted quantity cannot be negative.")

    # Lock only the quant row (FOR UPDATE can't apply to nullable outer joins).
    quant = StockQuant.objects.select_for_update(of=('self',)).get(pk=quant.pk)
    previous_qty = quant.quantity

    if expected_quantity is not None and previous_qty != Decimal(str(expected_quantity)):
        raise ValidationError(
            f"Stock changed since you counted (now {previous_qty}, you saw {expected_quantity}). "
            "Reload and recount.")

    diff = counted_qty - previous_qty
    if diff == 0:
        return None

    if counted_qty < quant.reserved_quantity:
        raise ValidationError(
            f"Counted quantity ({counted_qty}) is below the reserved quantity "
            f"({quant.reserved_quantity}). Unreserve the affected moves first.")

    location = quant.location
    product = quant.product
    company = quant.company
    warehouse = location.warehouse
    if warehouse is None:
        raise ValidationError(f'"{location.complete_name}" is not inside a warehouse; cannot adjust it.')

    # Capture cost BEFORE validate(): an incoming move may recompute average cost.
    unit_cost = product.product_cost

    adj_location = _adjustment_location(company)
    picking_type = _adjustment_picking_type(warehouse, adj_location)

    gain = diff > 0
    src, dest = (adj_location, location) if gain else (location, adj_location)
    qty = abs(diff)

    picking = StockPicking.objects.create(
        picking_type=picking_type, company=company,
        source_location=src, dest_location=dest,
        origin='Inventory adjustment',
        reason=reason or 'Physical Inventory Count Adjustment',
    )
    move = StockMove.objects.create(
        picking=picking, product=product, product_uom=product.uom, quantity=qty,
        lot=quant.lot, source_location=src, dest_location=dest,
    )
    StockMoveLine.objects.create(
        move=move, product=product, product_uom=product.uom, quantity=qty, lot=quant.lot,
        source_location=src, dest_location=dest,
        package=None if gain else quant.package,
        result_package=quant.package if gain else None,
    )

    picking.validate(create_backorder=False)

    inventory_adjustment_service(
        product, user, previous_qty, counted_qty, location,
        stock_move=move, picking=picking, company=company, unit_cost=unit_cost,
    )

    return picking


def _validate_transfer_destination(destination: StockLocation, company, source: StockLocation):
    if destination.pk == source.pk:
        raise ValidationError("Source and destination locations must be different.")
    if destination.company_id != company.pk:
        raise ValidationError("Destination location belongs to a different company.")
    if not destination.active:
        raise ValidationError(f'Destination "{destination.complete_name}" is archived.')
    if destination.usage != StockLocation.Usage.INTERNAL:
        raise ValidationError(
            f'Destination "{destination.complete_name}" is not an internal location. '
            "Internal transfers can only move stock between internal locations.")


@transaction.atomic
def transfer_stock(
        *,
        source_quant: StockQuant,
        quantity: Decimal,
        destination_location: StockLocation,
        source_location: StockLocation = None,   # optional; must match the quant if given
        user=None,
        reason: str = None,
        note: str = None,
) -> tuple[StockPicking, StockMove]:
    """
    Internal transfer of `quantity` from one quant to another internal location, as a real
    picking/move/line validated through the normal engine. Internal-to-internal within one
    company has no valuation impact, so no account move.
    """
    qty = Decimal(str(quantity))
    if qty <= 0:
        raise ValidationError("Transfer quantity must be strictly greater than 0.")
    if not source_quant:
        raise ValidationError("Source stock record (quant) not found.")

    quant = StockQuant.objects.select_for_update(of=('self',)).get(pk=source_quant.pk)
    src = quant.location

    if source_location and source_location.pk != src.pk:
        raise ValidationError("Source location does not match the quant's location.")
    if src.usage != StockLocation.Usage.INTERNAL:
        raise ValidationError(f'Source "{src.complete_name}" is not an internal location.')

    company = quant.company
    _validate_transfer_destination(destination_location, company, src)

    if qty > quant.quantity:
        raise ValidationError(
            f"Cannot transfer {qty}; only {quant.quantity} on hand at {src}.")
    free = quant.quantity - quant.reserved_quantity
    if qty > free:
        raise ValidationError(
            f"Insufficient available stock at {src}. Requested: {qty}, "
            f"Available: {free} ({quant.reserved_quantity} reserved).")

    types = StockPickingType.objects.filter(code=StockPickingType.Code.INTERNAL, active=True,
                                            warehouse__company=company)
    picking_type = types.filter(warehouse_id=src.warehouse_id).first() or types.first()
    if not picking_type:
        raise ValidationError("Picking type 'internal' missing for this company.")

    picking = StockPicking.objects.create(
        picking_type=picking_type, company=company,
        source_location=src, dest_location=destination_location,
        origin='Internal transfer', reason=reason or '', note=note or '',
        # created_by=user,   # uncomment if StockPicking has this field
    )
    move = StockMove.objects.create(
        picking=picking, product=quant.product, product_uom=quant.product.uom, quantity=qty,
        lot=quant.lot, source_location=src, dest_location=destination_location,
    )
    # Whole quant -> package moves intact. Partial -> stock leaves the package.
    StockMoveLine.objects.create(
        move=move, product=quant.product, product_uom=quant.product.uom, quantity=qty,
        lot=quant.lot, source_location=src, dest_location=destination_location,
        package=quant.package,
        result_package=quant.package if qty == quant.quantity else None,
    )

    picking.validate(create_backorder=False)
    return picking, move