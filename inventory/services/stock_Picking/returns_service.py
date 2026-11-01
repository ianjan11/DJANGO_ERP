from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from inventory.models import StockLocation, StockMove, StockPicking

ZERO = Decimal("0")


@transaction.atomic
def create_return_from_picking(picking, lines_data, user):
    """
    lines_data: [{"move_id": <StockMove pk>, "quantity": <Decimal>}, ...]
    Creates a confirmed return picking running the opposite direction of the
    original, using picking_type.return_picking_type. Validating it
    (picking.validate) moves the stock and posts valuation.
    """
    S = StockMove.Status

    # 1. lock + validate source picking
    picking = (
        StockPicking.objects.select_for_update()
        .select_related("picking_type", "source_location", "dest_location")
        .get(pk=picking.pk)
    )
    if picking.status != StockPicking.Status.COMPLETED:
        raise ValidationError("Only completed pickings can be returned.")

    internal = StockLocation.Usage.INTERNAL
    if (picking.source_location.usage == internal
            and picking.dest_location.usage == internal):
        raise ValidationError("Internal transfers cannot be returned.")

    return_type = picking.picking_type.return_picking_type
    if return_type is None or not return_type.active:
        raise ValidationError(
            f"Picking type '{picking.picking_type}' has no active return "
            "operation type configured.")

    if not lines_data:
        raise ValidationError("No lines selected to return.")

    # 2. normalise requested lines (merge duplicates)
    requested = {}
    for entry in lines_data:
        try:
            move_id = int(entry["move_id"])
            qty = Decimal(str(entry["quantity"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValidationError("Invalid return line.")
        if qty <= 0:
            raise ValidationError("Return quantity must be positive.")
        requested[move_id] = requested.get(move_id, ZERO) + qty

    # 3. lock original moves (serialises concurrent returns)
    originals = {
        m.pk: m
        for m in StockMove.objects.select_for_update(of=("self",))
        .select_related("product")
        .filter(picking=picking, status=S.COMPLETED, pk__in=requested)
    }
    missing = set(requested) - set(originals)
    if missing:
        raise ValidationError(
            f"Move(s) {sorted(missing)} are not completed moves of picking '{picking}'.")

    # 4. quantity guard
    for move_id, qty in requested.items():
        move = originals[move_id]
        remaining = get_remaining_return_quantity(move)
        if qty > remaining:
            raise ValidationError(
                f"Cannot return {qty} of '{move.product.name}': only "
                f"{remaining} remains returnable.")

    # 5. return picking, opposite direction
    return_picking = StockPicking.objects.create(
        picking_type=return_type,
        company=picking.company,
        partner=picking.partner,
        group=picking.group,
        sales_order=picking.sales_order,
        purchase_order=picking.purchase_order,
        source_location=picking.dest_location,
        dest_location=picking.source_location,
        origin=f"Return of {picking.name}"[:64],
        reason="Return",
        scheduled_date=timezone.now(),
    )

    for move_id, qty in requested.items():
        original = originals[move_id]

        # carry over the lot if the original moved exactly one
        lot_ids = set(original.lines.exclude(lot__isnull=True)
                      .values_list("lot_id", flat=True))
        lot_id = lot_ids.pop() if len(lot_ids) == 1 else None

        StockMove.objects.create(
            picking=return_picking,
            picking_type=return_type,
            product=original.product,
            company=original.company,
            quantity=qty,
            product_uom=original.product_uom,
            lot_id=lot_id,
            source_location=original.dest_location,
            dest_location=original.source_location,
            group=original.group,
            partner=original.partner,
            origin=return_picking.origin,
            sale_line=original.sale_line,
            purchase_line=original.purchase_line,
            origin_returned_move=original,
        )

    # 6. confirm + reserve (vendor returns leave internal stock, so must reserve)
    return_picking.action_assign()
    return_picking.refresh_from_db()
    return return_picking


def get_remaining_return_quantity(move):
    """What `move` moved, minus all non-cancelled returns pointing at it."""
    returned = (
        StockMove.objects
        .filter(origin_returned_move=move)
        .exclude(status=StockMove.Status.CANCELLED)
        .aggregate(total=Sum("quantity"))["total"]
        or ZERO
    )
    return move.quantity - returned




def get_returnable_lines(picking):
    """One row per completed move: delivered / already returned / remaining."""
    rows = []
    moves = (picking.moves
             .filter(status=StockMove.Status.COMPLETED)
             .select_related("product", "product_uom")
             .order_by("id"))
    for m in moves:
        remaining = get_remaining_return_quantity(m)
        rows.append({
            "move": m,
            "uom": m.product_uom or m.product.uom,
            "delivered": m.quantity,
            "returned": m.quantity - remaining,
            "remaining": remaining,
        })
    return rows