from enum import Enum

from django.core.exceptions import ValidationError


class Role(str, Enum):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"
    REVENUE = "revenue"
    EXPENSE = "expense"
    INVENTORY = "inventory"
    COGS = "cogs"
    STOCK_INPUT = "stock_input"            # GRNI
    STOCK_OUTPUT = "stock_output"          # GDNI
    PRICE_DIFFERENCE = "price_difference"
    ADJUSTMENT_GAIN = "adjustment_gain"
    ADJUSTMENT_EXPENSE = "adjustment_expense"
    REVALUATION_GAIN = "revaluation_gain"
    REVALUATION_EXPENSE = "revaluation_expense"
    CUSTOMER_CREDIT_NOTE = "customer_credit_note"
    VENDOR_CREDIT_NOTE = "vendor_credit_note"
    CUSTOMER_PREPAYMENT = "customer_prepayment"
    VENDOR_ADVANCE = "vendor_advance"


# Where each role is looked up, after the line account:
#   partner   : attribute on Partner
#   product   : attribute on Product
#   category  : method on ProductsCategory (walks up parents)
#   setting   : CompanyAccountSetting key
SPEC = {
    Role.RECEIVABLE: dict(partner="account_receivable", setting="default_receivable"),
    Role.PAYABLE: dict(partner="account_payable", setting="default_payable"),
    Role.REVENUE: dict(product="revenue_account", setting="default_revenue_account"),
    Role.EXPENSE: dict(product="expense_account"),
    Role.INVENTORY: dict(category="get_valuation_account", setting="default_inventory_valuation_account"),
    Role.COGS: dict(product="cogs_account", category="get_cogs_account", setting="default_cogs_account"),
    Role.STOCK_INPUT: dict(category="get_stock_input_account", setting="default_stock_input_account"),
    Role.STOCK_OUTPUT: dict(category="get_stock_output_account", setting="default_stock_output_account"),
    Role.PRICE_DIFFERENCE: dict(category="get_price_difference_account", setting="default_price_difference_account"),
    Role.ADJUSTMENT_GAIN: dict(setting="default_inventory_adjustment_gain"),
    Role.ADJUSTMENT_EXPENSE: dict(setting="default_inventory_adjustment_expense"),
    Role.REVALUATION_GAIN: dict(setting="default_inventory_revaluation_gain"),
    Role.REVALUATION_EXPENSE: dict(setting="default_inventory_revaluation_expense"),
    Role.CUSTOMER_CREDIT_NOTE: dict(setting="default_customer_credit_note_account"),
    Role.VENDOR_CREDIT_NOTE: dict(setting="default_vendor_credit_note_account"),
    Role.CUSTOMER_PREPAYMENT: dict(setting="default_customer_prepayments"),
    Role.VENDOR_ADVANCE: dict(setting="default_vendor_advances"),
}

SALE_TYPES = ("out_invoice", "out_refund")


def invoice_line_role(product, move_type):
    """The role an invoice/credit-note PRODUCT line posts to."""
    if move_type in SALE_TYPES:
        return Role.REVENUE
    if product is not None and product.product_type == "storable":
        return Role.INVENTORY
    return Role.EXPENSE


def _line_primary_role(line):
    if not line.move_id:
        return None
    return invoice_line_role(line.product, line.move.move_type)


def _as_account(value):
    if value is None or hasattr(value, "pk"):
        return value
    from accounting.models import Account
    return Account.objects.filter(pk=value).first()


def resolve_account(role, *, company, line=None, product=None, partner=None,
                    settings_map=None, fallback=None, required=True):
    """
    First hit wins:
      1. the line's own account   (only for that line's PRIMARY role)
      2. partner override         (receivable / payable)
      3. product field
      4. product category         (inherits from parents)
      5. company default setting
      6. `fallback` role's company default
    """
    role = Role(role)
    spec = SPEC[role]
    product = product or getattr(line, "product", None)
    cache = {"settings": settings_map}

    def setting(key):
        if cache["settings"] is None:
            cache["settings"] = company.get_settings_dict()
        return cache["settings"].get(key)

    def candidates():
        # Primary-role guard: a customer line's account is REVENUE, so it must
        # never be returned for the COGS / GDNI / inventory legs of the same line.
        if line is not None and line.account_id and role == _line_primary_role(line):
            yield "line", line.account
        if partner is not None and spec.get("partner"):
            yield "partner", getattr(partner, spec["partner"], None)
        if product is not None:
            if spec.get("product"):
                yield "product", getattr(product, spec["product"], None)
            if spec.get("category") and product.category_id:
                yield "category", getattr(product.category, spec["category"])()
        if spec.get("setting"):
            yield "company default", setting(spec["setting"])
        if fallback:
            fb = SPEC[Role(fallback)].get("setting")
            if fb:
                yield "company fallback", setting(fb)

    for source, value in candidates():
        account = _as_account(value)
        if not account:
            continue
        if account.company_id != company.pk:
            raise ValidationError(f"{role.value} account '{account}' (from {source}) belongs to another company.")
        if not account.is_active:
            raise ValidationError(f"{role.value} account '{account}' (from {source}) is inactive.")
        return account

    if not required:
        return None
    where = ", ".join(k for k in ("partner", "product", "category", "setting") if k in spec) or "company settings"
    raise ValidationError(
        f"No {role.value.replace('_', ' ')} account configured"
        + (f" for '{product.name}'" if product else "")
        + f". Set it on: {where}.")