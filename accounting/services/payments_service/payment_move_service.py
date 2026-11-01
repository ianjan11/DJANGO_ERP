"""
Builds the double-entry AccountMove for a Payment.

Kept separate from the Payment model so that GL-construction logic
(which accounts, which lines, in what order) doesn't live on the model
alongside intent/state. Payment.confirm() calls build_payment_account_move()
and attaches the result; this module never saves the Payment itself.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError


# ======================================================================
# ACCOUNT RESOLUTION
# ======================================================================

def resolve_counterpart_account(payment):
    """
    Resolve the AR / AP counterpart account for a payment.

    Order of resolution:
      1. If the payment already has invoice allocations, reuse the
         reconciliation account on the first allocated invoice line —
         keeps the payment's GL account consistent with what it's
         actually being matched against.
      2. Otherwise, fall back to the company's default receivable /
         payable account for the payment's partner_type.

    TRANSFER payments have no counterpart account.
    """
    from accounting.models import CompanyAccountSetting

    if payment.payment_type == 'TRANSFER':
        return None

    if hasattr(payment, 'invoice_allocations') and payment.invoice_allocations.exists():
        first_alloc = payment.invoice_allocations.select_related('invoice_move').first()
        line = first_alloc.invoice_move.lines.filter(
            account__allow_reconciliation=True
        ).first()
        if line:
            return line.account

    if payment.partner_type == 'customer':
        setting_key = 'default_receivable'
    elif payment.partner_type == 'supplier':
        setting_key = 'default_payable'
    else:
        setting_key = (
            'default_receivable'
            if payment.payment_type == 'INCOMING'
            else 'default_payable'
        )

    try:
        return CompanyAccountSetting.objects.get(
            company=payment.company, key=setting_key
        ).account
    except CompanyAccountSetting.DoesNotExist:
        raise ValidationError(f"Accounting configuration missing for: {setting_key}")

def _resolve_liquidity_account(payment):
    liquidity_account = payment.journal.get_liquidity_account(payment.payment_type)
    if not liquidity_account:
        raise ValidationError(
            f"Journal '{payment.journal}' has no account configured for "
            f"{payment.payment_type} payments."
        )
    return liquidity_account

def _resolve_counterpart_for_build(payment):
    settings_map = payment.company.get_settings_dict()

    if payment.is_prepayment:
        if payment.payment_type == 'INCOMING':
            counterpart_account = settings_map.get('default_customer_prepayments')
        else:
            counterpart_account = settings_map.get('default_vendor_advances')

        if not counterpart_account:
            counterpart_account = resolve_counterpart_account(payment)
    else:
        counterpart_account = resolve_counterpart_account(payment)

    return counterpart_account


# ======================================================================
# LINE CONSTRUCTION
# ======================================================================

def _build_lines(payment, move, liquidity_account, counterpart_account):
    from accounting.models import AccountMoveLine

    amt = payment.amount_company_currency
    amt_ccy = payment.amount
    is_foreign = payment.currency != payment.company.currency

    if payment.payment_type == 'INCOMING':
        # DR Bank, CR AR
        return [
            AccountMoveLine(
                move=move, account=liquidity_account, partner=payment.partner,
                debit=amt, credit=Decimal('0'),
                original_amount=amt_ccy if is_foreign else Decimal('0'),
                foreign_currency=payment.currency if is_foreign else None,
                date=payment.date, memo=payment.ref or payment.payment_number,
                line_type=AccountMoveLine.LineType.RECEIVABLE,

            ),
            AccountMoveLine(
                move=move, account=counterpart_account, partner=payment.partner,
                debit=Decimal('0'), credit=amt,
                original_amount=-amt_ccy if is_foreign else Decimal('0'),
                foreign_currency=payment.currency if is_foreign else None,
                date=payment.date, memo=payment.ref or payment.payment_number,
                line_type=AccountMoveLine.LineType.RECEIVABLE,

            ),
        ]

    if payment.payment_type == 'OUTGOING':
        # DR AP, CR Bank
        return [
            AccountMoveLine(
                move=move, account=counterpart_account, partner=payment.partner,
                debit=amt, credit=Decimal('0'),
                original_amount=amt_ccy if is_foreign else None,
                foreign_currency=payment.currency if is_foreign else None,
                date=payment.date, memo=payment.ref or payment.payment_number,
                line_type=AccountMoveLine.LineType.RECEIVABLE

            ),
            AccountMoveLine(
                move=move, account=liquidity_account, partner=payment.partner,
                debit=Decimal('0'), credit=amt,
                original_amount=-amt_ccy if is_foreign else None,
                foreign_currency=payment.currency if is_foreign else None,
                date=payment.date, memo=payment.ref or payment.payment_number,
                line_type=AccountMoveLine.LineType.RECEIVABLE

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
            date=payment.date, memo=payment.ref or payment.payment_number,
            line_type = AccountMoveLine.LineType.RECEIVABLE

        ),
        AccountMoveLine(
            move=move, account=liquidity_account,
            debit=Decimal('0'), credit=amt,
            date=payment.date, memo=payment.ref or payment.payment_number,
            line_type = AccountMoveLine.LineType.RECEIVABLE

        ),
    ]


# ======================================================================
# ENTRY POINT
# ======================================================================

def build_payment_account_move(payment, user, move_type="payment"):
    """
    Constructs, saves and posts the double-entry AccountMove for `payment`.

    INCOMING (customer pays us):
        DR  Bank / Cash          (journal default debit account)
        CR  Accounts Receivable  (partner's AR account)

    OUTGOING (we pay vendor):
        DR  Accounts Payable     (partner's AP account)
        CR  Bank / Cash          (journal default credit account)

    TRANSFER (internal):
        DR  Destination journal's default debit account
        CR  Source journal's default credit account

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

    move.save(update_fields=['amount_total', 'amount_untaxed','amount_residual'])

    move.post(user)

    return move