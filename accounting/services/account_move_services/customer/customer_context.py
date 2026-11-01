from decimal import Decimal
from django.core.exceptions import ValidationError

from accounting.services.account_move_services.customer.get_open_gdni import get_open_gdni_entries
from accounting.services.account_move_services.shared.account_utils import resolve_line_account, round2
from accounting.services.account_move_services.customer.sales_gdni_account_move import _get_stock_output_account
from accounting.services.account_move_services.shared.invoice.clearing import (
    allocate_open_entries,
    delivered_qty,
    invoiced_qty,
    netted_sales_return_qty,
    open_total,
)

ZERO = Decimal("0.00")


# ================================================================
# CUSTOMER LINE ACCOUNTING CONTEXT
# ================================================================

def get_customer_context(invoice, item, product, item_amount_ccy, state):
    """
    Revenue leg (primary) + for storable products the COGS / GDNI / inventory
    legs (secondary). `state` is the invoice-wide ClearingState.
    """
    item_amount_ccy = _validate_item_amount(item_amount_ccy)
    allocations = []

    revenue_account = (
        item.account if item.account else resolve_line_account(item, invoice, "revenue")
    )
    allocations.append({
        "account": revenue_account,
        "amount": item_amount_ccy,
        "side": "CREDIT",
        "source": "revenue",
        "is_primary": True,
        "gdni_allocations": [],
    })

    if product.product_type == "storable":
        allocations.extend(_build_cogs_allocations(invoice, item, product, state))
    elif product.product_type not in ("service", "consumable"):
        raise ValidationError(f"Unsupported product type: {product.product_type}")

    return {"allocations": allocations}


# ================================================================
# COGS / GDNI / INVENTORY (storable only)
# ================================================================

def _build_cogs_allocations(invoice, item, product, state):
    """
    For an invoiced quantity q of a sale line:

      * delivered-but-not-yet-invoiced qty (pending) is cleared against GDNI:
        Dr COGS / Cr GDNI for exactly the open delivery cost it represents
        (the whole open amount when this invoice completes the pending qty,
        so no cents are left open).
      * any qty NOT yet delivered is costed at product_cost:
        Dr COGS / Cr Inventory. The delivery later skips these units
        (see create_valuation_for_picking), so inventory is credited once.
    """
    qty = _item_qty(item)
    unit_cost = _positive_decimal(product.product_cost)

    cogs_account = resolve_line_account(item, invoice, "cogs")
    inventory_account = resolve_line_account(item, invoice, "inventory")

    gdni_allocations, cleared_qty = [], ZERO

    open_gdnis = list(get_open_gdni_entries(invoice, item, for_update=True))
    if open_gdnis:
        order_line = item.source_line
        pending_qty = (
            delivered_qty(order_line)
            - netted_sales_return_qty(order_line)
            - invoiced_qty(order_line, ("out_invoice",), exclude_move=invoice)
            - state.qty[order_line.pk]
        )
        available = open_total(open_gdnis, "gdni", state)

        if pending_qty > ZERO and available > ZERO:
            cleared_qty = min(qty, pending_qty)
            if cleared_qty >= pending_qty:
                target = available
            else:
                target = round2(available * cleared_qty / pending_qty)
            gdni_allocations, _ = allocate_open_entries(open_gdnis, target, "gdni", state)
            state.qty[order_line.pk] += cleared_qty

    gdni_amount = sum((a["amount"] for a in gdni_allocations), ZERO)
    undelivered_cost = round2((qty - cleared_qty) * unit_cost)
    total_cost = round2(gdni_amount + undelivered_cost)

    allocations = [{
        "account": cogs_account,
        "amount": total_cost,
        "side": "DEBIT",
        "source": "cogs",
        "is_primary": False,
        "gdni_allocations": [],
    }]

    if gdni_amount > ZERO:
        gdni_account = _get_stock_output_account(product)
        if not gdni_account:
            raise ValidationError(f"Product '{product.name}' has no Stock Output / GDNI account.")
        allocations.append({
            "account": gdni_account,
            "amount": gdni_amount,
            "side": "CREDIT",
            "source": "gdni",
            "is_primary": False,
            "gdni_allocations": gdni_allocations,
        })

    if undelivered_cost > ZERO:
        allocations.append({
            "account": inventory_account,
            "amount": undelivered_cost,
            "side": "CREDIT",
            "source": "inventory_clearing",
            "is_primary": False,
            "gdni_allocations": [],
        })

    return allocations


# ================================================================
# HELPERS
# ================================================================

def _item_qty(item):
    qty = item.quantity_in_storage_uom
    if qty is None or Decimal(str(qty)) <= ZERO:
        raise ValidationError(f"Invoice line {item.pk} needs a positive quantity.")
    return Decimal(str(qty))


def _validate_item_amount(amount):
    amount = Decimal(amount)
    if amount < ZERO:
        raise ValidationError("Customer invoice line amount cannot be negative.")
    return amount


def _positive_decimal(value):
    if value is None:
        return ZERO
    value = Decimal(str(value))
    return value if value > ZERO else ZERO