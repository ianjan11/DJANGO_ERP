from decimal import Decimal

from django.db.models import Sum, Q

from accounting.models import PartialReconcile, AccountMove


def get_reconciliation_candidate_moves(payment):
    """All AccountMoves relevant to reconciling this payment: its own
    move plus any prepayment-swap moves generated for it."""
    candidates = [payment.account_move]
    if payment.is_prepayment:
        candidates.extend(
            AccountMove.objects.filter(
                is_prepayment_swap=True,
                origin_type="payment",
                origin_id=payment.id,
            ).exclude(id=payment.account_move_id)
        )
    return candidates


def _get_all_payment_ar_lines(payment):
    """
    Every AR/AP line ever created for this payment — its own account_move's
    line, plus any prepayment-swap moves' lines — regardless of whether the
    line has since been flagged reconciled=True.

    Unlike _get_payment_ar_lines (which filters reconciled=False and is
    meant for "what's still available to match against"), this is meant
    for "what's the payment's total position" — a line must not disappear
    from this view just because it became fully matched, or the payment
    would incorrectly look unpaid at the exact moment it becomes paid.
    """
    candidate_moves = get_reconciliation_candidate_moves(payment)

    lines = []
    for move in candidate_moves:
        if payment.payment_type == 'INCOMING':
            qs = move.lines.filter(
                credit__gt=0, debit=0, account__allow_reconciliation=True
            )
        else:
            qs = move.lines.filter(
                debit__gt=0, credit=0, account__allow_reconciliation=True
            )
        lines.extend(qs)

    return lines

def _payment_reconciliation_summary(payment):
    """
    Returns (lines, reconciled_amount, residual) for a payment, where:
      - lines: every AR/AP line ever created for this payment (see above)
      - reconciled_amount: total matched across those lines, however many
        there are and regardless of individual reconciled flags
      - residual: payment.amount_company_currency - reconciled_amount

    This single formula is correct for both direct payments (one line,
    full capacity == amount_company_currency) and prepayment payments
    (many partial lines; unswapped money contributes no line and
    therefore correctly never counts as reconciled).
    """
    lines = _get_all_payment_ar_lines(payment)

    if not lines:
        return lines, Decimal('0'), payment.amount_company_currency

    reconciled_amount = PartialReconcile.objects.filter(
        Q(debit_line__in=lines) | Q(credit_line__in=lines)
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    residual = payment.amount_company_currency - reconciled_amount
    return lines, reconciled_amount, residual
