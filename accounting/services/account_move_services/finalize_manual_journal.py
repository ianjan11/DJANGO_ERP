from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from accounting.models import AccountMoveLine


def finalize_manual_journal_post(move, user):
    """
    Completes a manually-created AccountMove before posting.

    Manual journal creation/editing only ever touches UPDATABLE_FIELDS —
    on the move: journal, partner, date, narration, ref, payment_term;
    on lines: account, debit, credit, memo. Everything derivable from
    those (totals, per-line partner/date, name, residual) is filled in
    here at post time, rather than in AccountMove.post(), because post()
    is shared by flows (payment creation, prepayment swap) that already
    populate those fields themselves and shouldn't have this logic
    silently overwrite what they set.

    Must be called with move locked (select_for_update) and inside the
    same transaction as the caller's state-transition check.
    """
    lines = list(move.lines.all())

    if len(lines) < 2:
        raise ValidationError(
            "A journal entry needs at least two lines."
        )

    if not move.is_balanced():
        raise ValidationError("Cannot post an unbalanced journal entry.")

    total = move.total_debit  # == total_credit, since is_balanced() passed
    if total <= Decimal('0'):
        raise ValidationError(
            "Cannot post a journal entry with a zero total — "
            "check that line amounts were entered."
        )

    # Lines never carry partner/date in a manual journal — always copy
    # both down from the move.
    for line in lines:
        if not  line.partner_id:
          line.partner_id = move.partner_id
        line.date = move.issue_date

    AccountMoveLine.objects.bulk_update(lines, ['partner', 'date'])

    # Assign sequence number — manual journals don't get a name at
    # creation time.
    if not move.name:
        move.name = move.journal.get_next_number()

    # Totals — manual journals have no separate tax lines, so untaxed
    # equals total.
    move.amount_total = total
    move.amount_untaxed = total

    move.state = 'posted'
    move.posted_by = user
    move.posted_at = timezone.now()
    move.save(update_fields=[
        'name', 'amount_total', 'amount_untaxed', 'state', 'posted_by', 'posted_at',
    ])

    # Seed amount_residual for any reconcilable (AR/AP) lines — nothing
    # has been reconciled yet, so this just reflects the freshly-posted
    # totals rather than the default 0.
    if move.lines.filter(account__allow_reconciliation=True).exists():
        move.update_residual()

    return move