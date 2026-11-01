import logging
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST
from django.db import transaction
from django.core.exceptions import ValidationError
from accounting.forms import PaymentForm
from accounting.services.payments_service.payment_loader import load_payment
from accounting.services.payments_service.payment_state_service import PaymentStateService
from core.utils import htmx_error, htmx_success

logger = logging.getLogger('sales.invoice')



def get_empty_payment_form(request):
    partner_type = request.GET.get("partner_type", "").lower()


    form = PaymentForm(
        company=request.company,
    )

    if partner_type == "supplier":
        back_url = reverse("accounting:vendor_payments")
    else:
        back_url = reverse("accounting:customer_payments")

    context = {
        "payment_form": form,
        "back_url": back_url,
        "partner_type": partner_type,
    }

    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/payments_templates/partials/payment_form_partial.html",
            context,
        )

    return render(
        request,
        "accounting/payments_templates/payment_form.html",
        context,
    )

@require_http_methods(["POST"])
def save_pre_payments(request):
    company = getattr(request, "company", None)
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"paymentFailed": {"message": "User has no company assigned."}},
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

    payment = form.save(commit=False)
    payment.state = "draft"
    payment.created_by = request.user
    payment.is_prepayment = True

    try:
        with transaction.atomic():
            payment.full_clean()
            payment.save()

        detail_url = reverse(
            "accounting:payment_details", kwargs={"payment_id": payment.id}
        )

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
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
            trigger={"paymentFailed": {"message": "Failed to save payment due to an internal error."}},
        )

    return htmx_success(
        request,
        "Payment saved successfully.",
        trigger={"paymentSuccess": {"message": "Payment saved successfully."}},
        redirect_url=detail_url,
        target="#accounting-display",
    )

@require_POST
def edit_payments(request, payment_id):
    company = getattr(request.user, "company", None)
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"paymentFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            payment = load_payment(payment_id, request, for_update=True)

            state_service = PaymentStateService()
            if not state_service.is_editable(payment):
                return htmx_error(
                    request,
                    "Cannot edit this payment because it is in a non-editable state.",
                    trigger={"paymentFailed": {"message": "Payment is not in an editable state."}},
                )

            if not payment.is_prepayment:
                return htmx_error(
                    request,
                    "Cannot edit payments that are attached to an invoice.",
                    trigger={"paymentFailed": {"message": "Cannot edit payments attached to invoices."}},
                )

            form = PaymentForm(request.POST, user=request.user, instance=payment)
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

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"paymentValidationError": {"errors": errors}},

        )

    except Exception:
        logger.exception("Unexpected error occurred during payment update")
        return htmx_error(
            request,
            "Failed to save payment due to an internal server error.",
            trigger={"paymentFailed": {"message": "Failed to save payment due to an internal error."}},
        )

    return htmx_success(
        request,
        "Payment updated successfully.",
        trigger={"paymentSuccess": {"message": "Payment updated successfully."}},
        target="#accounting-display",
    )




