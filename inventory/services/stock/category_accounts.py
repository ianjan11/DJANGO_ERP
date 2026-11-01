# inventory/services/stock/category_accounts.py
from django.core.exceptions import ValidationError

from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company,
    get_company_account,
)

# ================================================================
# CONFIGURATION
# ================================================================

# Category field -> CompanyAccountSetting key.
# The first three keys are the ones your GRNI / GDNI services already use.
# The rest are ASSUMPTIONS -- rename them to match your settings.
# Fields that don't exist on ProductsCategory yet (revenue / expense) are
# skipped automatically, so they start working as soon as you add them.
CATEGORY_ACCOUNT_SOURCES = {
    "property_valuation_account":        "default_inventory_valuation_account",
    "property_stock_input_account":      "default_stock_input_account",
    "property_stock_output_account":     "default_stock_output_account",
    "property_cogs_account":             "default_cogs_account",
    "property_price_difference_account": "default_price_difference_account",
    "property_revenue_account":          "default_revenue_account",
    "property_expense_account":          "default_expense_account",
}


# ================================================================
# HELPERS
# ================================================================

def _company_default(company, key):
    """Company default, or None instead of raising when it isn't configured."""
    try:
        return get_company_account(company, key=key)
    except ValidationError:
        return None


def _getter_for(category, field):
    """'property_cogs_account' -> category.get_cogs_account (or None)."""
    return getattr(category, "get_" + field[len("property_"):], None)


# ================================================================
# PUBLIC ENTRY POINT
# ================================================================

def populate_category_accounts(category):
    """
    Fill BLANK accounting properties on a new category.

    For each property:
        1. already set on the category          -> left alone
        2. a parent category already provides it -> left blank, so the
           child keeps INHERITING live (get_*_account walks up the parents)
        3. otherwise                              -> company default, if configured

    Unlike populate_product_accounts this never raises: a missing company
    default just leaves the property blank. The product service is the one
    that enforces required accounts, at the point where they're needed.

    Mutates `category` in memory and returns it; the caller saves it.
    Requires category.company to be set already.
    """
    if not category.company_id:
        raise ValidationError("Category needs a company before accounts can be assigned.")

    model_fields = {f.name for f in category._meta.fields}

    for field, company_key in CATEGORY_ACCOUNT_SOURCES.items():
        if field not in model_fields:
            continue  # property not added to the model yet

        if getattr(category, f"{field}_id"):
            continue  # user chose one

        getter = _getter_for(category, field)
        if category.parent_id and getter and getter():
            continue  # inherited from an ancestor

        account = _company_default(category.company, company_key)
        if account is None:
            continue

        assert_same_company(
            account, category.company, field.replace("property_", "").replace("_", " ").title()
        )
        setattr(category, field, account)

    return category