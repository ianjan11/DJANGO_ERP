from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove
from accounting.services import create_payload, reverse_move


@transaction.atomic
def cancel_posted_payment_service(payment, user):
    if payment.state != 'posted':
        raise ValidationError("The payment is not posted.")

    if payment.payment_state in ('partial', 'paid'):
        raise ValidationError(
            "Cannot cancel a payment that is partially or fully reconciled. "
            "Unreconcile first."
        )

    if payment.is_prepayment:
        swap_moves = AccountMove.objects.filter(
            is_prepayment_swap=True,
            origin_type="payment",
            origin_id=payment.id,
        )
        for swap_move in swap_moves:
            if swap_move.lines.filter(reconciled=True).exists():
                raise ValidationError(
                    "Cannot cancel this payment: its prepayment swap entry has "
                    "already been reconciled against an invoice. Unreconcile first."
                )
        # any unreconciled swap moves are orphaned — reverse them as part of cancellation
        for swap_move in swap_moves:
            reverse_move(
                payload=create_payload(
                    ref=payment.payment_number, amount=swap_move.amount_total,
                    source="payment", reason="cancelled",
                    origin_type="account_move", origin_id=swap_move.pk,
                ),
                user=user,
            )


    reversal_payload = create_payload(
            ref=payment.payment_number,
            amount=payment.amount,
            source="payment",
            reason="cancelled",
            origin_type="payment",
            origin_id=payment.pk,
        )

    reversal_move = reverse_move(payload=reversal_payload, user=user)

    payment.state = 'cancelled'
    payment.reversal_move = reversal_move
    payment.save(update_fields=['state', 'reversal_move'])



def cancel_draft_payment_service(payment):

    if payment.state != 'draft':
        raise ValidationError(
            "only draft payments can be cancelled."
        )

    if payment.payment_state in ('partial', 'paid'):
         raise ValidationError(
                "Cannot cancel a payment that is partially or fully reconciled. "
                "Unreconcile first."
            )

    payment.state = 'cancelled'
    payment.save(update_fields=['state'])






