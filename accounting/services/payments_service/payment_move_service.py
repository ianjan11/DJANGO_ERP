"""
Builds the double-entry AccountMove for a Payment.

Kept separate from the Payment model so that GL-construction logic
(which accounts, which lines, in what order) doesn't live on the model
alongside intent/state. Payment.confirm() calls build_payment_account_move()
and attaches the result; this module never saves the Payment itself.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from accounting.services.account_resolver import Role, resolve_account


# ======================================================================
# ACCOUNT RESOLUTION
# ======================================================================

def _allocated_invoice_account(payment):
    """
    If the payment is already allocated to invoices, reuse the receivable /
    payable control account of the first allocated invoice, so the payment
    posts to the same account it will be reconciled against.

    Only the control line counts: an invoice also carries GRNI/GDNI lines
    on reconcilable accounts, which must never be picked up here.
    """
    from accounting.models import AccountMoveLine

    if not hasattr(payment, 'invoice_allocations'):
        return None

    first_alloc = (
        payment.invoice_allocations
        .select_related('invoice_move')
        .first()
    )
    if first_alloc is None:
        return None

    line = (
        first_alloc.invoice_move.lines
        .filter(
            line_type=AccountMoveLine.LineType.RECEIVABLE,
            account__allow_reconciliation=True,
        )
        .select_related('account')
        .first()
    )
    return line.account if line else None


def _is_customer_side(payment):
    if payment.partner_type == 'customer':
        return True
    if payment.partner_type == 'supplier':
        return False
    return payment.payment_type == 'INCOMING'


def resolve_counterpart_account(payment):
    """
    Resolve the AR / AP counterpart account for a payment.

      1. Reuse the account of the first allocated invoice (if any).
      2. Otherwise the resolver: partner account, then company default.

    TRANSFER payments have no counterpart account.
    """
    if payment.payment_type == 'TRANSFER':
        return None

    account = _allocated_invoice_account(payment)
    if account is not None:
        return account

    role = Role.RECEIVABLE if _is_customer_side(payment) else Role.PAYABLE
    return resolve_account(
        role,
        company=payment.company,
        partner=payment.partner,
    )


def _resolve_liquidity_account(payment):
    liquidity_account = payment.journal.get_liquidity_account(payment.payment_type)
    if not liquidity_account:
        raise ValidationError(
            f"Journal '{payment.journal}' has no account configured for "
            f"{payment.payment_type} payments."
        )
    return liquidity_account


def _resolve_counterpart_for_build(payment):
    if payment.payment_type == 'TRANSFER':
        return None

    if payment.is_prepayment:
        role = (
            Role.CUSTOMER_PREPAYMENT
            if payment.payment_type == 'INCOMING'
            else Role.VENDOR_ADVANCE
        )
        return resolve_account(
            role,
            company=payment.company,
            partner=payment.partner,
        )

    return resolve_counterpart_account(payment)


# ======================================================================
# LINE CONSTRUCTION
# ======================================================================

def _build_lines(payment, move, liquidity_account, counterpart_account):
    from accounting.models import AccountMoveLine

    LT = AccountMoveLine.LineType

    amt = payment.amount_company_currency
    amt_ccy = payment.amount
    is_foreign = payment.currency != payment.company.currency
    memo = payment.ref or payment.payment_number
    fx = payment.currency if is_foreign else None

    if payment.payment_type == 'INCOMING':
        # DR Bank, CR AR
        return [
            AccountMoveLine(
                move=move, account=liquidity_account, partner=payment.partner,
                debit=amt, credit=Decimal('0'),
                original_amount=amt_ccy if is_foreign else Decimal('0'),
                foreign_currency=fx, date=payment.date, memo=memo,
                line_type=LT.PLAIN,
            ),
            AccountMoveLine(
                move=move, account=counterpart_account, partner=payment.partner,
                debit=Decimal('0'), credit=amt,
                original_amount=-amt_ccy if is_foreign else Decimal('0'),
                foreign_currency=fx, date=payment.date, memo=memo,
                line_type=LT.RECEIVABLE,
            ),
        ]

    if payment.payment_type == 'OUTGOING':
        # DR AP, CR Bank
        return [
            AccountMoveLine(
                move=move, account=counterpart_account, partner=payment.partner,
                debit=amt, credit=Decimal('0'),
                original_amount=amt_ccy if is_foreign else None,
                foreign_currency=fx, date=payment.date, memo=memo,
                line_type=LT.RECEIVABLE,
            ),
            AccountMoveLine(
                move=move, account=liquidity_account, partner=payment.partner,
                debit=Decimal('0'), credit=amt,
                original_amount=-amt_ccy if is_foreign else None,
                foreign_currency=fx, date=payment.date, memo=memo,
                line_type=LT.PLAIN,
            ),
        ]

    # TRANSFER
    dest_account = payment.destination_journal.default_debit_account
    if not dest_account:
        raise ValidationError(
            f"Destination journal '{payment.destination_journal}' has no "
            f"default debit account configured."
        )
    return [
        AccountMoveLine(
            move=move, account=dest_account,
            debit=amt, credit=Decimal('0'),
            date=payment.date, memo=memo, line_type=LT.PLAIN,
        ),
        AccountMoveLine(
            move=move, account=liquidity_account,
            debit=Decimal('0'), credit=amt,
            date=payment.date, memo=memo, line_type=LT.PLAIN,
        ),
    ]


# ======================================================================
# ENTRY POINT
# ======================================================================

def build_payment_account_move(payment, user, move_type="payment"):
    """
    Constructs, saves and posts the double-entry AccountMove for `payment`.

    INCOMING (customer pays us):
        DR  Bank / Cash          (journal liquidity account)
        CR  Accounts Receivable  (allocated invoice / partner / company default)

    OUTGOING (we pay vendor):
        DR  Accounts Payable     (allocated invoice / partner / company default)
        CR  Bank / Cash          (journal liquidity account)

    TRANSFER (internal):
        DR  Destination journal's default debit account
        CR  Source journal's liquidity account

    Prepayments use the customer-prepayment / vendor-advance accounts instead
    of AR / AP.

    Returns the posted AccountMove. Does NOT save `payment` — the caller
    (Payment.confirm()) attaches it (payment.account_move = move) and saves.
    Requires payment.id to already be set (origin_id on the move).
    """
    from accounting.models import AccountMove, AccountMoveLine

    liquidity_account = _resolve_liquidity_account(payment)
    counterpart_account = _resolve_counterpart_for_build(payment)

    number = payment.journal.get_next_number()  # atomic, holds the lock

    move = AccountMove(
        name=number,
        move_type=move_type,
        issue_date=payment.date,
        partner=payment.partner,
        currency=payment.currency,
        currency_rate=payment.currency_rate,
        company=payment.company,
        journal=payment.journal,
        ref=payment.payment_number,
        narration=payment.memo,
        created_by=user,
        origin_type='payment',
        origin_id=payment.id,
    )
    move.save()

    lines = _build_lines(payment, move, liquidity_account, counterpart_account)
    AccountMoveLine.objects.bulk_create(lines)

    move.amount_total = payment.amount_company_currency
    move.amount_untaxed = payment.amount_company_currency
    move.amount_residual = payment.amount_company_currency
    move.save(update_fields=['amount_total', 'amount_untaxed', 'amount_residual'])

    move.post(user)

    return move