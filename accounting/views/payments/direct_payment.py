import logging
from decimal import Decimal

from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.core.exceptions import ValidationError
from accounting.forms import PaymentForm
from accounting.services import check_invoice_payment_lock
from accounting.services.account_move_services.account_move_loader import load_account_move
from accounting.services.payment_line import create_payment_line
from accounting.services.payments_service.payment_state_service import PaymentStateService
from core.utils import htmx_success, htmx_error

logger = logging.getLogger(__name__)


@require_http_methods(["POST"])
def save_payments(request):

    company = getattr(request, "company", None)
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"paymentFailed": {"message": "User has no company assigned."}},
        )

    invoice_id = request.POST.get("invoice_id")
    if not invoice_id:
        return htmx_error(
            request,
            "Invoice ID is required.",
            trigger={"paymentFailed": {"message": "Invoice ID is required."}},
        )

    form = PaymentForm(request.POST, user=request.user, company=company)
    form.instance.company = company

    if not form.is_valid():
        errors = {
            field: [str(e) for e in error_list]
            for field, error_list in form.errors.items()
        }
        return htmx_error(
            request,
            errors,
            trigger={"paymentValidationError": {"errors": errors}},
        )

    try:
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.state = "draft"
            payment.created_by = request.user

            if payment.payment_type == "OUTGOING":
                allowed_move_types = ["in_invoice", "out_refund"]
            else:
                allowed_move_types = ["out_invoice", "in_refund"]

            invoice_move = load_account_move(invoice_id, request, for_update=True)


            if not invoice_move:
                return htmx_error(
                    request,
                    f"Invoice with ID {invoice_id} not found or not valid.",
                    trigger={
                        "paymentFailed": {
                            "message": "Invoice not found or not valid."
                        }
                    },
                )

            check_invoice_payment_lock(
                invoice_move=invoice_move,
                new_payment_amount=payment.amount,
                exclude_payment_id=None,
            )

            payment.full_clean()
            payment.save()

            create_payment_line(payment, invoice_move, payment.amount)

            state_service = PaymentStateService()
            result = state_service.transition(payment, state_service.POSTED)
            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This payment cannot be posted right now."
                )

            payment.confirm(request)

    except ValidationError as e:
        errors = (
            e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        )
        return htmx_error(
            request,
            errors,
            trigger={"paymentValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during payment creation")
        return htmx_error(
            request,
            "Failed to save payment due to an internal server error.",
            trigger={
                "paymentFailed": {
                    "message": "Failed to save payment due to an internal error."
                }
            },
        )

    return htmx_success(
        request,
        "Payment saved successfully.",
        trigger={"paymentSuccess": {"message": "Payment saved successfully."}},
    )