from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError

from accounting.services.account_resolver import resolve_account, Role

_KIND = {"revenue": Role.REVENUE, "expense": Role.EXPENSE,
         "inventory": Role.INVENTORY, "cogs": Role.COGS}


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


from accounting.services.account_resolver import resolve_account, Role, SPEC

_KEY_ROLE = {s["setting"]: r for r, s in SPEC.items() if "setting" in s}

def get_company_account(company, key: str):
    role = _KEY_ROLE.get(key)
    if role:
        return resolve_account(role, company=company)
    from accounting.models import CompanyAccountSetting   # keys not modelled as roles (cash, bank, ...)
    try:
        return CompanyAccountSetting.objects.get(company=company, key=key).account
    except CompanyAccountSetting.DoesNotExist:
        raise ValidationError(f"No '{key}' account configured for company '{company}'.")

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



def resolve_line_account(item, invoice, kind):
    return resolve_account(_KIND[kind], company=invoice.company, line=item)


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
