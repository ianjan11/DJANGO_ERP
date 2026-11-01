# accounting/migrations/000X_seed_account_types.py
from django.db import migrations

ACCOUNT_TYPES = {
    "account_type_liquidity":              {"name": "Cash and Cash Equivalents",   "internal_group": "ASSET"},
    "account_type_receivable":             {"name": "Receivable",                  "internal_group": "ASSET"},
    "account_type_current_assets":         {"name": "Current Assets",              "internal_group": "ASSET"},
    "account_type_fixed_assets":           {"name": "Fixed Assets",                "internal_group": "ASSET"},
    "account_type_prepayments":            {"name": "Prepayments",                 "internal_group": "ASSET"},
    "account_type_non_current_assets":     {"name": "Non-current Assets",          "internal_group": "ASSET"},
    "account_type_payable":                {"name": "Payable",                     "internal_group": "LIABILITY"},
    "account_type_credit_card":            {"name": "Credit Card",                 "internal_group": "LIABILITY"},
    "account_type_current_liabilities":    {"name": "Current Liabilities",         "internal_group": "LIABILITY"},
    "account_type_non_current_liabilities":{"name": "Non-current Liabilities",     "internal_group": "LIABILITY"},
    "account_type_equity":                 {"name": "Equity",                      "internal_group": "EQUITY"},
    "account_type_equity_unaffected":      {"name": "Current Year Earnings",       "internal_group": "EQUITY"},
    "account_type_revenue":                {"name": "Income",                      "internal_group": "INCOME"},
    "account_type_other_income":           {"name": "Other Income",                "internal_group": "INCOME"},
    "account_type_expenses":               {"name": "Expenses",                    "internal_group": "EXPENSE"},
    "account_type_direct_costs":           {"name": "Cost of Revenue",             "internal_group": "EXPENSE"},
    "account_type_depreciation":           {"name": "Depreciation",                "internal_group": "EXPENSE"},
    "account_type_other_expense":          {"name": "Other Expense",               "internal_group": "EXPENSE"},
}


def create_account_types(apps, schema_editor):
    AccountType = apps.get_model('accounting', 'AccountType')

    for code, data in ACCOUNT_TYPES.items():
        AccountType.objects.update_or_create(
            code=code,
            defaults={
                "name": data["name"],
                "internal_group": data["internal_group"],
            }
        )


def delete_account_types(apps, schema_editor):
    AccountType = apps.get_model('accounting', 'AccountType')
    codes = list(ACCOUNT_TYPES.keys())
    AccountType.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0003_initial'),  # <-- set to whichever migration adds AccountType.code
    ]

    operations = [
        migrations.RunPython(create_account_types, delete_account_types),
    ]