from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def round2(val) -> Decimal:
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# determine_invoice
# ---------------------------------------------------------------------------

# def _get_type(invoice):
#     customer_invoice = None
#     PurchaseInvoice = None
#
#     if invoice in PurchaseInvoice
#

# ---------------------------------------------------------------------------
# Private helpers — reused by both invoice and return services
# ---------------------------------------------------------------------------


def get_company_account(company, key: str):
    from accounting.models import CompanyAccountSetting

    """Fetch a company-level default GL account or raise ValidationError."""
    try:
        return CompanyAccountSetting.objects.get(
            company=company, key=key
        ).account
    except CompanyAccountSetting.DoesNotExist:
        raise ValidationError(
            f"No '{key}' account configured for company '{company}'. "
            "Add it in Company Account Settings."
        )


def assert_reconcilable(account, label: str) -> None:
    if not account.allow_reconciliation:
        raise ValidationError(
            f"Account '{account}' must have 'Allow Reconciliation' enabled "
            f"to be used as a {label} account."
        )


def assert_same_company(account, company, label: str) -> None:
    if account.company_id != company.pk:
        raise ValidationError(
            f"{label} '{account}' does not belong to company '{company}'."
        )



def compute_due_date(invoice):
    """
    Return the actual due date from the invoice's payment term.
    Falls back to the invoice date when no payment term is set.
    """
    if not invoice.payment_term:
        return invoice.issue_date

    # Find the BALANCE line (last instalment — determines final due date)
    last_line = (
        invoice.payment_term.lines
        .filter(computation_type="BALANCE")
        .order_by("-sequence")
        .first()
    )
    if last_line:
        from datetime import timedelta
        return invoice.issue_date + timedelta(days=last_line.days)

    return invoice.issue_date


from accounting.models import AccountMoveLine

def make_move_line(
    *,
    move,
    account,
    partner,
    debit: Decimal,
    credit: Decimal,
    date,
    memo: str,
    foreign_currency,
    original_amount: Decimal = Decimal("0"),
    line_type: str = AccountMoveLine.LineType.PLAIN,
    stock_move = None,

) -> AccountMoveLine:



    if foreign_currency:
        amount_currency = round2(original_amount if debit > 0 else -original_amount)
    else:
        amount_currency = Decimal("0")

    return AccountMoveLine(
        move=move,
        account=account,
        line_type=line_type,
        partner=partner,
        debit=debit,
        credit=credit,
        original_amount=amount_currency,
        foreign_currency=foreign_currency,
        date=date,
        memo=memo,
    )

def resolve_line_account(item, invoice, account_type):
    product = item.product
    category = product.category

    if account_type == "revenue":
        if product.revenue_account:
            return product.revenue_account

        account = category.get_revenue_account()
        if account:
            return account

    elif account_type == "cogs":
        if product.cogs_account:
            return product.cogs_account

        account = category.get_cogs_account()
        if account:
            return account

    elif account_type == "expense":
        if product.expense_account:
            return product.expense_account

        account = category.get_expense_account()
        if account:
            return account

    elif account_type == "inventory":
        account = category.get_valuation_account()
        if account:
            return account

    elif account_type == "stock_input":
        account = category.get_stock_input_account()
        if account:
            return account

    raise ValidationError(
        f"No {account_type} account configured for "
        f"product '{product.name}'."
    )


def get_company_journal(company, key: str):
    """Fetch a company-level default journal or raise ValidationError."""
    from accounting.models.company_accounts import CompanyJournalSetting

    try:
        return CompanyJournalSetting.objects.get(company=company, key=key).journal
    except CompanyJournalSetting.DoesNotExist:
        raise ValidationError(
            f"No '{key}' journal configured for company '{company}'. "
            "Add it in Company Journal Settings."
        )
