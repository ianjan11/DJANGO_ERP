from django.core.exceptions import ValidationError
from django.db import transaction
from accounting.models import AccountMoveLine, AccountMove
from decimal import Decimal
import logging
from accounting.services.payments_service.payment_move_service import resolve_counterpart_account
logger = logging.getLogger("accounting.reconciliation")


@transaction.atomic
def swap_move_prepayments(payment, user):
    """
    Creates the prepayment-swap AccountMove for a payment: moves the full
    payment amount out of the customer/vendor advance account into AR/AP,
    unlocking it to be used in later reconciliations.

    Applies once, to the whole payment — not chunked, not repeatable.
    Callers must hold a row lock on payment (e.g. via
    load_payment(..., for_update=True)) before calling this, and should
    check PaymentStateService.can_apply_prepayment first; the guard below
    is a backstop, not a substitute for that lock.

    This only swaps accounts in company currency — original_amount and
    foreign_currency are intentionally left unset on these lines. The
    swap doesn't represent a new currency-denominated transaction; it's
    a reclassification of the original move's amount between accounts.
    """
    if AccountMove.objects.filter(
        origin_type="payment", origin_id=payment.id, is_prepayment_swap=True
    ).exists():
        raise ValidationError(
            f"Payment {payment.payment_number} has already had its "
            f"prepayment swap applied."
        )

    settings_map = payment.company.get_settings_dict()

    number = payment.journal.get_next_number()
    move = AccountMove.objects.create(
        name=number, move_type="entry", issue_date=payment.date,
        partner=payment.partner, currency=payment.currency,
        currency_rate=payment.currency_rate, company=payment.company,
        journal=payment.journal, ref=f"Reconcile: {payment.payment_number}",
        created_by=user, origin_id=payment.id, origin_type="payment",
        is_prepayment_swap=True,
    )

    amt_ccy = payment.amount_company_currency

    lines = []
    if payment.payment_type == "INCOMING":
        adv_account = settings_map.get('default_customer_prepayments')
        rec_account = resolve_counterpart_account(payment)
        lines.append(AccountMoveLine(
            move=move, account=adv_account, partner=payment.partner,
            debit=amt_ccy, credit=Decimal('0'),
        ))
        lines.append(AccountMoveLine(
            move=move, account=rec_account, partner=payment.partner,
            debit=Decimal('0'), credit=amt_ccy,
        ))
    elif payment.payment_type == "OUTGOING":
        adv_account = settings_map.get('default_vendor_advances')
        pay_account = resolve_counterpart_account(payment)
        lines.append(AccountMoveLine(
            move=move, account=pay_account, partner=payment.partner,
            debit=amt_ccy, credit=Decimal('0'),
        ))
        lines.append(AccountMoveLine(
            move=move, account=adv_account, partner=payment.partner,
            debit=Decimal('0'), credit=amt_ccy,
        ))
    else:
        raise ValidationError(
            f"Prepayment swap is not supported for payment_type "
            f"'{payment.payment_type}'."
        )

    AccountMoveLine.objects.bulk_create(lines)
    move.amount_total = amt_ccy
    move.amount_untaxed = amt_ccy
    move.amount_residual = amt_ccy
    move.save(update_fields=['amount_total', 'amount_untaxed', 'amount_residual'])
    move.post(user)
    return move