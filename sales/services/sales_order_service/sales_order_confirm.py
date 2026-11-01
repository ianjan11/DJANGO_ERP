from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.services.stock_Picking.procurement_engine import DemandLine, procure_delivery


@transaction.atomic
def confirm_sales_order(order):
    """
    Confirm a DRAFT sales order: assign the order number, compute and save totals,
    set the status, and pass stock-tracked items to the procurement engine.

    Returns the ProcurementGroup of the delivery, or None if the order has no stock lines.

    Raises:
        ValidationError: If the order is not a draft or has no items.
        ProcurementException: If procurement rules/routes fail (the whole confirm rolls back).
        ValueError: If warehouse delivery configuration is missing.
    """
    # Lock the row and re-read the status, so a double click cannot confirm twice
    # (which would run the procurement twice and create duplicate deliveries).
    type(order).objects.select_for_update().get(pk=order.pk)
    order.refresh_from_db(fields=["status"])
    # ASSUMPTION: adjust to your SalesOrder status names.
    if order.status != "DRAFT":
        raise ValidationError("Only draft orders can be confirmed.")

    if not order.has_items():
        raise ValidationError("Order has no items.")

    # 1. Update order header and totals
    order_number = order.order_number
    if not order_number:
        from sales.services.sales_order_service.creator import generate_order_number
        order_number = generate_order_number(company=order.company)

    untaxed, tax, total = order.compute_amounts()

    order.order_number = order_number
    order.status = "CONFIRMED"      # was listed in update_fields but never set
    order.confirmed_at = timezone.now()
    order.amount_untaxed = untaxed
    order.amount_tax = tax
    order.amount_total = total
    order.payment_state = "not_paid"
    order.save(update_fields=[
        "order_number", "status", "confirmed_at",
        "amount_untaxed", "amount_tax", "amount_total", "payment_state",
    ])

    # 2. Stock-tracked lines only
    stock_lines = [
        line for line in order.lines.select_related("product")
        if line.product.is_stockable
    ]
    if not stock_lines:
        return None

    # 3. Build demand and run the procurement engine
    demand_lines = [
        DemandLine(
            product=line.product,
            quantity=Decimal(str(line.quantity)),
            uom= line.product_uom or line.product.uom,
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
        # `or`, not a getattr default: an expected_date that exists but is None would
        # otherwise reach the engine as None and crash on `date_planned - timedelta`.
        date_planned=getattr(order, "expected_date", None) or timezone.now(),
        partner=getattr(order, "partner", None),
        sales_order=order,
        reserve=True,
    )

    return delivery_result.group