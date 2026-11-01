from decimal import Decimal
from django.core.exceptions import ValidationError
from accounting.services.account_move_services.shared.account_utils import resolve_line_account
from accounting.services.account_move_services.shared.invoice.clearing import allocate_open_entries
from accounting.services.account_move_services.vendor.get_open_grni import get_open_grni_entries
from accounting.services.account_move_services.vendor.purchase_grni_account_move import _get_stock_input_account


# ================================================================
# VENDOR LINE ACCOUNTING CONTEXT
# ================================================================

def get_vendor_context(invoice, item, product, item_amount_ccy, state):
    """
    Resolve the accounting context for a vendor invoice line.

    The returned context contains one or more account allocations.
    All allocations on a vendor bill represent primary base expenses/assets
    and carry `is_primary: True`.

    Examples:

        Service:
            Expense       100,000

        Storable, no receipt:
            Inventory     100,000

        Storable, fully received:
            GRNI          100,000

        Storable, partially received:
            GRNI           60,000
            Inventory      40,000

        Consumable:
            Expense       100,000
    """

    item_amount_ccy = _validate_item_amount(item_amount_ccy)

    if product.product_type in ("service", "consumable"):
        return _build_expense_context(
            invoice=invoice,
            item=item,
            item_amount_ccy=item_amount_ccy,
        )

    if product.product_type == "storable":
        return _build_storable_context(
            invoice=invoice,
            item=item,
            product=product,
            item_amount_ccy=item_amount_ccy,
            state=state,
        )

    raise ValidationError(
        f"Unsupported product type: {product.product_type}"
    )


# ================================================================
# SERVICE / CONSUMABLE
# ================================================================

def _build_expense_context(invoice, item, item_amount_ccy):


    account = item.account if item.account else resolve_line_account(item, invoice, "expense")

    return {
        "allocations": [
            {
                "account": account,
                "amount": item_amount_ccy,
                "side": "DEBIT",  # Explicit polarity
                "source": "expense",
                "is_primary": True,  # Primary Base Leg
                "grni_allocations": [],
            }
        ]
    }


# ================================================================
# STORABLE
# ================================================================

def _build_storable_context(invoice, item, product, item_amount_ccy, state):
    """
    Resolve a storable vendor invoice line.

    The invoice amount may be:
        1. entirely normal inventory
        2. entirely GRNI
        3. partially GRNI and partially inventory
    """

    inventory_account = resolve_line_account(item, invoice, "inventory")

    open_grnis = _get_locked_open_grnis(invoice, item)

    if not open_grnis:
        return _build_inventory_context(
            inventory_account=inventory_account,
            item_amount_ccy=item_amount_ccy,
        )

    grni_allocations, total_grni = allocate_open_entries(
        open_grnis, item_amount_ccy, "grni", state
    )

    if total_grni <= Decimal("0.00"):
        return _build_inventory_context(
            inventory_account=inventory_account,
            item_amount_ccy=item_amount_ccy,
        )

    grni_amount = sum(
        (allocation["amount"] for allocation in grni_allocations),
        Decimal("0.00"),
    )

    normal_amount = item_amount_ccy - grni_amount

    allocations = []

    if grni_amount > Decimal("0.00"):
        grni_account = _get_stock_input_account(product)
        if not grni_account:
            raise ValidationError(
                f"Product '{product.name}' has no Stock Input / GRNI account configured."
            )

        allocations.append(
            {
                "account": grni_account,
                "amount": grni_amount,
                "side": "DEBIT",  # Explicit polarity (clears GRNI liability)
                "source": "grni",
                "is_primary": True,  # Primary Base Leg
                "grni_allocations": grni_allocations,
            }
        )

    if normal_amount > Decimal("0.00"):
        allocations.append(
            {
                "account": inventory_account,
                "amount": normal_amount,
                "side": "DEBIT",  # Explicit polarity (increases inventory asset directly)
                "source": "inventory",
                "is_primary": True,  # Primary Base Leg
                "grni_allocations": [],
            }
        )

    return {"allocations": allocations}


# ================================================================
# INVENTORY ONLY
# ================================================================

def _build_inventory_context(inventory_account, item_amount_ccy):
    return {
        "allocations": [
            {
                "account": inventory_account,
                "amount": item_amount_ccy,
                "side": "DEBIT",  # Explicit polarity
                "source": "inventory",
                "is_primary": True,  # Primary Base Leg
                "grni_allocations": [],
            }
        ]
    }


# ================================================================
# GET OPEN GRNI
# ================================================================

def _get_locked_open_grnis(invoice, item):
    """
    Fetch open GRNI entries and lock them for the duration of the
    invoice-posting transaction. Must be called inside an atomic
    block — select_for_update() requires an open transaction.
    """

    return list(get_open_grni_entries(invoice, item, for_update=True))


# ================================================================
# VALIDATION / DECIMAL HELPERS
# ================================================================

def _validate_item_amount(amount):
    amount = Decimal(amount)

    if amount < Decimal("0.00"):
        raise ValidationError(
            "Vendor invoice line amount cannot be negative."
        )

    return amount


def _positive_decimal(value):
    if value is None:
        return Decimal("0.00")

    value = Decimal(value)

    if value < Decimal("0.00"):
        return Decimal("0.00")

    return value