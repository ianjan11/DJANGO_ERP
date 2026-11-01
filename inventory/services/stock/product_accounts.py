# inventory/services/stock/product_accounts.py
from django.core.exceptions import ValidationError

from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company,
    get_company_account,
)

# ================================================================
# CONFIGURATION
# ================================================================

# Product field -> (ProductsCategory getter, CompanyAccountSetting key).
# NOTE: the company keys for revenue / cogs / expense are assumptions --
# rename them to whatever you actually store in CompanyAccountSetting.
PRODUCT_ACCOUNT_SOURCES = {
    "revenue_account": ("get_revenue_account", "default_revenue_account"),
    "cogs_account":    ("get_cogs_account",    "default_cogs_account"),
    "expense_account": ("get_expense_account", "default_expense_account"),
}

# Which product-level accounts each product type actually needs.
FIELDS_BY_PRODUCT_TYPE = {
    "storable":   ("revenue_account", "cogs_account"),
    "consumable": ("revenue_account", "expense_account"),
    "service":    ("revenue_account", "expense_account"),
}

# Accounts that live on the category (not on Product) but are required later
# by the GRNI / GDNI / invoice services for automated storable products.
# (label, category getter, company key)
STOCK_ACCOUNT_CHECKS = (
    ("inventory valuation", "get_valuation_account",    "default_inventory_valuation_account"),
    ("stock input (GRNI)",  "get_stock_input_account",  "default_stock_input_account"),
    ("stock output (GDNI)", "get_stock_output_account", "default_stock_output_account"),
)


# ================================================================
# HELPERS
# ================================================================

def _from_category(category, getter_name):
    """Category lookup (walks up parents). Tolerates a getter that doesn't exist yet."""
    getter = getattr(category, getter_name, None)
    return getter() if getter else None


def _from_company(company, key):
    """Company default, or None instead of raising when it isn't configured."""
    try:
        return get_company_account(company, key=key)
    except ValidationError:
        return None


def _resolve(product, getter_name, company_key):
    """Category first (inherits through parents), then company default."""
    account = _from_category(product.category, getter_name)
    return account or _from_company(product.company, company_key)


# ================================================================
# PUBLIC ENTRY POINT
# ================================================================

def populate_product_accounts(product):
    """
    Fill any BLANK product-level GL accounts on a new product.

    Resolution order per account:
        1. value already set on the product (never overwritten)
        2. product category (inherited through parent categories)
        3. company default (CompanyAccountSetting)

    Mutates `product` in memory and returns it -- the caller saves it, so the
    whole thing is one INSERT. Raises a single ValidationError listing every
    account that could not be resolved, so a misconfigured product fails at
    creation instead of later when an invoice or picking is posted.

    Requires product.company and product.category to be set already.
    """
    if not product.company_id or not product.category_id:
        raise ValidationError(
            "Product needs a company and a category before accounts can be assigned."
        )

    missing = []

    # -- 1. product-level accounts ---------------------------------
    for field in FIELDS_BY_PRODUCT_TYPE.get(product.product_type, ()):
        if getattr(product, f"{field}_id"):
            continue  # respect what the user chose

        getter_name, company_key = PRODUCT_ACCOUNT_SOURCES[field]
        account = _resolve(product, getter_name, company_key)

        if account is None:
            missing.append(field.replace("_", " "))
            continue

        assert_same_company(account, product.company, field.replace("_", " ").title())
        setattr(product, field, account)

    # -- 2. category-level stock accounts (validate only) ----------
    if (
        product.product_type == "storable"
        and product.get_valuation_method() == "automated"
    ):
        for label, getter_name, company_key in STOCK_ACCOUNT_CHECKS:
            if _resolve(product, getter_name, company_key) is None:
                missing.append(f"{label} (category or company default)")

    if missing:
        raise ValidationError(
            f"Cannot assign accounts for '{product.name}'. Missing: "
            + ", ".join(missing)
            + ". Set them on the product category or in Company Account Settings."
        )

    return product