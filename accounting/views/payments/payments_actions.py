from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from accounting.events.accounting_events import create_event
from accounting.events.types import AccountingEventType
from accounting.forms import PaymentForm
import logging
from accounting.services.payments_service.apply_pre_payment import swap_move_prepayments
from accounting.services.payments_service.payment_loader import load_payment
from accounting.services.payments_service.payment_state_service import PaymentStateService
from accounting.services.payments_service.payment_updates import cancel_posted_payment_service, \
    cancel_draft_payment_service
from core.events import dispatch
from core.utils import htmx_error, htmx_success

logger = logging.getLogger(__name__)

def payment_details(request, payment_id):

    payment = load_payment(payment_id, request, for_update=True)

    context = _build_context(request, payment)


    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/payments_templates/partials/payment_details_partial.html",
            context,
        )


    return render(
        request,
        "accounting/payments_templates/payment_details.html",
        context,
    )

@require_POST
@login_required
def post_payment_view(request, payment_id):
    detail_url = reverse("accounting:payment_details", kwargs={"payment_id": payment_id})

    try:
        with transaction.atomic():

            payment = load_payment(payment_id, request, for_update=True)

            state_service = PaymentStateService()

            result = state_service.transition(payment, state_service.POSTED)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This payment cannot be posted right now."
                )

            # Execution logic / GL side effects (confirm creates AccountMove, assigns number, etc.)
            payment.confirm(request)

            event = create_event(
                event_type=AccountingEventType.PAYMENT_POSTED,
                payload={
                    "payment_id": payment.pk,
                    "payment_number": payment.payment_number,
                    "partner_id": payment.partner_id,
                    "amount": str(payment.amount),
                    "payment_type": payment.payment_type,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, "message") else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to post payment %s", payment_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Payment Posted Successfully",
        redirect_url=detail_url,
        target="#accounting-display",
    )

@require_POST
@login_required
def cancel_payment_view(request, payment_id):
    detail_url = reverse(
        "accounting:payment_details",
        kwargs={"payment_id": payment_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock payment
            payment = load_payment(
                payment_id=payment_id,
                request=request,
                for_update=True,
            )

            # 2. Company-level permission guard
            if payment.company != request.company:
                return htmx_error(request, "Unauthorized.", detail_url)

            # 3. Document ownership guard
            if (
                not request.user.is_staff
                and payment.created_by != request.user
            ):
                raise PermissionDenied

            state_service = PaymentStateService()

            # 4. Capture state BEFORE transition checks
            previous_state = payment.state

            # 5. Authorization based on original state
            if not request.user.is_staff:
                if previous_state != state_service.DRAFT:
                    raise PermissionDenied(
                        "You are not allowed to cancel this payment."
                    )

            # 6. State service performs ALL workflow transition rules
            result = state_service.transition(
                payment,
                state_service.CANCELLED,
            )

            if not result.get("success"):
                errors = result.get("errors")

                if isinstance(errors, dict):
                    messages = []
                    for field_errors in errors.values():
                        messages.extend(field_errors)

                    raise ValidationError(
                        messages
                        or "This payment cannot be cancelled right now."
                    )

                raise ValidationError(
                    errors
                    or "This payment cannot be cancelled right now."
                )

            # 7. Execute dedicated path based on previous state
            if previous_state == state_service.DRAFT:
                cancel_draft_payment_service(payment)
            elif previous_state == state_service.POSTED:
                if not request.user.is_staff:
                    raise PermissionDenied(
                        "Administrative permission is required "
                        "to cancel a posted payment."
                    )
                cancel_posted_payment_service(payment, request.user)

            # 8. Event dispatch
            event = create_event(
                event_type=AccountingEventType.PAYMENT_CANCELLED,
                payload={
                    "payment_id": payment.pk,
                    "payment_number": payment.payment_number,
                    "partner_id": payment.partner_id,
                    "previous_state": previous_state,
                    "new_state": state_service.CANCELLED,
                    "account_move_reversed": bool(payment.reversal_move_id),
                    "reversal_move_id": payment.reversal_move_id,
                },
                user_id=request.user.pk,
                source=(
                    "htmx"
                    if request.headers.get("HX-Request")
                    else "web"
                ),
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        if hasattr(e, "messages"):
            message = " ".join(e.messages)
        else:
            message = str(e)

        return htmx_error(
            request,
            message,
            detail_url,
        )

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to cancel this payment.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to cancel payment %s",
            payment_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Payment cancelled successfully.",
        redirect_url=detail_url,
        target="#accounting-display",
    )


@require_POST
@login_required
def apply_pre_payment_view(request, payment_id):
    detail_url = reverse("accounting:payment_details", kwargs={"payment_id": payment_id})

    try:
        with transaction.atomic():

            payment = load_payment(payment_id, request, for_update=True)

            state_service = PaymentStateService()

            can_apply = state_service.can_apply_prepayment(payment)

            if not can_apply:
                raise ValidationError(
                    "This payment cannot be applied right now."
                )


            swap_move_prepayments(payment,user=request.user)

            event = create_event(
                event_type=AccountingEventType.PAYMENT_POSTED,
                payload={
                    "payment_id": payment.pk,
                    "payment_number": payment.payment_number,
                    "partner_id": payment.partner_id,
                    "amount": str(payment.amount),
                    "payment_type": payment.payment_type,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, "message") else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to apply pre_payment %s", payment_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Payment Applied Successfully Please Reconcile open invoices",
        redirect_url=detail_url,
        target="#accounting-display",
    )


def _build_context(request, payment):

    payment_form = PaymentForm(user=request.user, instance=payment)


    context = {
        "payment": payment,
        "payment_form": payment_form,
        "partner_type": payment.partner_type,
    }

    return context



