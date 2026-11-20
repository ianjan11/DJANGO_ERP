from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.utils.extract_errors import extract_first_error
from inventory.services.stock_Picking.procurement_engine import DemandLine, procure_delivery
from sales.services.sales_order_service.sales_order_state_service import SalesOrdersStateService

_state = SalesOrdersStateService()


@transaction.atomic
def confirm_sales_order(order):
    """
    Confirm a SENT sales order: validate + apply the status transition,
    assign the order number, compute totals, and run procurement.

    Returns the ProcurementGroup of the delivery, or None if there are no stock lines.

    Raises:
        ValidationError: transition not allowed / already confirmed / no partner or lines.
        ProcurementException: procurement fails (whole confirm rolls back).
        ValueError: warehouse delivery configuration is missing.
    """
    # 1. Lock the row and sync the in-memory status with the DB, so a double
    #    click or a stale object can never confirm twice.
    type(order).objects.select_for_update().get(pk=order.pk)
    order.refresh_from_db(fields=["status"])

    # 2. The state service is the single source of truth for the status change.
    #    It also rejects "already CONFIRMED", which is what blocks double confirms.
    result = _state.transition(order, _state.CONFIRMED)
    if not result.get("success"):
        raise ValidationError(
            extract_first_error(
                result.get("errors"),
                "This sales order cannot be confirmed right now.",
            )
        )
    # order.status is now CONFIRMED in memory; persisted in the save below.

    # 3. Header + totals
    order_number = order.order_number
    if not order_number:
        from sales.services.sales_order_service.creator import generate_order_number
        order_number = generate_order_number(company=order.company)

    untaxed, tax, total = order.compute_amounts()

    order.order_number = order_number
    order.confirmed_at = timezone.now()
    order.amount_untaxed = untaxed
    order.amount_tax = tax
    order.amount_total = total
    order.payment_state = "not_paid"
    order.save(update_fields=[
        "order_number", "status", "confirmed_at",
        "amount_untaxed", "amount_tax", "amount_total",
        "payment_state", "updated_at",
    ])

    # 4. Stock-tracked lines only
    stock_lines = [
        line for line in order.lines.select_related("product")
        if line.product.is_stockable
    ]
    if not stock_lines:
        return None

    demand_lines = [
        DemandLine(
            product=line.product,
            quantity=Decimal(str(line.quantity)),
            uom=line.product_uom or line.product.uom,
            sale_line=line,
            packaging=getattr(line, "packaging", None),
            route_ids=tuple(line.routes.values_list("pk", flat=True)) if hasattr(line, "routes") else (),
        )
        for line in stock_lines
    ]

    delivery_result = procure_delivery(
        name=order.order_number or order.name,
        company=order.company,
        warehouse=order.fulfillment_location,
        lines=demand_lines,
        date_planned=getattr(order, "expected_date", None) or timezone.now(),
        partner=getattr(order, "partner", None),
        sales_order=order,
        reserve=True,
    )

    return delivery_result.group