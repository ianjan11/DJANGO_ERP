import logging
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


# ---------------------------------------------------------------------------
# 1. Lock checker — call this BEFORE saving the payment
# ---------------------------------------------------------------------------

def check_invoice_payment_lock(invoice_move, new_payment_amount: Decimal, exclude_payment_id=None):

    from accounting.models import PaymentInvoiceLine

    locked_statuses = ('draft', 'posted')

    qs = PaymentInvoiceLine.objects.select_for_update().filter(
        invoice_move=invoice_move,
        payment__state__in=locked_statuses,
    )

    if exclude_payment_id is not None:
        qs = qs.exclude(payment_id=exclude_payment_id)

    accumulated = qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    invoice_total = invoice_move.amount_total
    projected = accumulated + new_payment_amount

    if accumulated >= invoice_total:
        raise ValidationError(
            f"Payment blocked: Invoice {invoice_move.name} is already fully covered. "
            f"Invoice total: {invoice_total:.2f} | "
            f"Already allocated (draft + confirmed): {accumulated:.2f}."
        )

    if projected > invoice_total:
        remaining = invoice_total - accumulated
        raise ValidationError(
            f"Payment blocked: This payment of {new_payment_amount:.2f} would exceed "
            f"Invoice {invoice_move.name} total ({invoice_total:.2f}). "
            f"Maximum allowed: {remaining:.2f}."
        )


def _has_payment_in_states(invoice_move, states, exclude_payment_id=None):

    from accounting.models import Payment, PaymentInvoiceLine

    if invoice_move is None:
        return False
    qs = PaymentInvoiceLine.objects.select_for_update().filter(
        invoice_move=invoice_move,
        payment__state__in=states,
    )
    if exclude_payment_id is not None:
        qs = qs.exclude(payment_id=exclude_payment_id)
    return qs.exists()

def has_pending_payment(invoice_move, exclude_payment_id=None):
    return _has_payment_in_states(invoice_move, ('draft', 'posted'), exclude_payment_id)

def has_completed_payment(invoice_move, exclude_payment_id=None):
    return _has_payment_in_states(invoice_move, ('reconciled',), exclude_payment_id)