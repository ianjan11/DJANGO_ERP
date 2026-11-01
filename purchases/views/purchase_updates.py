from django.template.loader import render_to_string
from pygments.lexers import data
from django.http import  HttpResponseBadRequest, Http404
from core.services.document_service.core.payload_builder import build_payload
import json
import logging
from django.http import HttpResponse
from django.urls import reverse
from pygments.lexers import data
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect,  get_object_or_404
from core.events import dispatch
from core.services.document_service.document_service import DocumentService
from core.services.document_service.presentation.htmx_swap_service import UIResponseService
from core.utils import htmx_error, htmx_success
from inventory.models.procurement_group import ProcurementException
from purchases.events.purchase_events import create_event
from purchases.forms import PurchaseOrderLineFormSet, PurchaseOrderForm
from purchases.models import PurchaseOrderLine, PurchaseOrder
from purchases.services.creator import create_purchase
from purchases.services.purchase_order_loader import load_purchase_order
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from inventory.models import Product, StockPicking
from purchases.events.types import PurchaseEventType
from django.shortcuts import render

from purchases.services.purchase_state_service import PurchaseOrdersStateService

logger = logging.getLogger("purchases.invoice")

def _build_context(request, purchase, header_form, formset):
    from django.core.paginator import Paginator

    products = Product.objects.filter(
        company=request.company
    )

    lines = (
        PurchaseOrderLine.objects
        .filter(purchase_order=purchase)
        .prefetch_related("shipment_lines")
        .order_by("-id")
        if purchase
        else PurchaseOrderLine.objects.none()
    )

    paginator = Paginator(lines, 10)
    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return {
        "purchase": purchase,
        "header_form": header_form,
        "formset": formset,
        "products": products,
        "lines": page_obj,
        "is_new": purchase is None,
    }



@login_required
def purchase_create_or_detail(request, purchase_id=None):

    # ─────────────────────────────────────
    # CREATE FLOW
    # ─────────────────────────────────────
    if not purchase_id:
        try:
            with transaction.atomic():
                purchase = create_purchase(request, company_id=request.company.id)

                event = create_event(
                    event_type=PurchaseEventType.PURCHASE_CREATED,
                    user_id=request.user.id,
                    source="htmx" if request.headers.get('HX-Request') else "web",
                    payload={
                        "purchase_id": purchase.id
                    }
                )

                transaction.on_commit(lambda: dispatch(event))

        except Exception as e:
            logger.exception("Failed to create purchase: %s", e)
            messages.error(request, "Something went wrong. Please try again.")
            return htmx_error(request,"Failed to initialize draft document. Please try again.")


        return redirect("purchases:purchase_create_or_detail", purchase_id=purchase.id)

    # ─────────────────────────────────────
    # LOAD FLOW
    # ─────────────────────────────────────
    purchase = load_purchase_order(purchase_id, request)

    header_form = PurchaseOrderForm(
        request.POST or None,
        instance=purchase,
        company=request.company
    )

    formset = PurchaseOrderLineFormSet(
        request.POST or None,
        instance=purchase,
        prefix="items",
        form_kwargs={"doc": purchase},
    )

    if request.method == "POST":
        if header_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                header_form.save()
                formset.save()
            messages.success(request, "Purchase order saved.")
            return redirect("purchases:purchase_create_or_detail", purchase_id=purchase.id)
        else:
            messages.error(request, "Please fix the errors below.")

    context = _build_context(
        request=request,
        purchase=purchase,
        header_form=header_form,
        formset=formset,
    )

    if request.headers.get("HX-Request"):
        return render(request, "purchases/partials/purchase_detail_partial.html", context)

    return render(request, "purchases/purchase_detail.html", context)


def purchase_line_row(request, purchase_id):

    purchase = load_purchase_order(purchase_id, request)

    partner_id = purchase.partner_id

    if not partner_id:
        return htmx_error(request, "Please Select Partner first and try again.")

    prefix = request.GET.get('prefix', 'items')
    total_forms = int(request.GET.get('total_forms', 0))

    formset = PurchaseOrderLineFormSet(
        instance=purchase,
        prefix=prefix,
        form_kwargs={"doc": purchase},
    )

    form = formset.empty_form
    form.prefix = f"{prefix}-{total_forms}"

    html = render_to_string(
        'purchases/partials/purchase_item_row.html',
        {'form': form, 'purchase': purchase},
        request=request,
    )
    return HttpResponse(html)

def purchase_update(request):

    if request.method != "POST":
        return HttpResponse(status=405)

    order_id = request.POST.get("purchase_id")


    if not order_id:
        return HttpResponseBadRequest("Missing order_id")

    order = load_purchase_order(
        purchase_id=order_id, request=request,for_update=True
    )

    try:
        payload, dropped_unsaved_rows = build_payload(request.POST, doc_type="purchase_order")

    except ValidationError as e:
        return htmx_error(
            message=e.message,
            request=request,
        )

    try:
        context = DocumentService().apply_state(
            doc_instance=order,
            payload=payload,
            dropped_unsaved_rows=dropped_unsaved_rows,
            request=request,
            user=request.user,
        )
    except Exception:
        logger.exception("apply_state failed for order_id=%s", order_id)
        raise

    return UIResponseService().render(request=request, payload=context)

def purchase_totals(request, purchase_id):
    purchase = get_object_or_404(PurchaseOrder, pk=purchase_id)
    return render(request, 'purchases/partials/purchase_totals.html', {'purchase': purchase})

@login_required
def confirm_purchase(request, purchase_id):

    detail_url = reverse("purchases:purchase_create_or_detail", kwargs={"purchase_id": purchase_id})

    try:
        with transaction.atomic():
            purchase = load_purchase_order(purchase_id=purchase_id, request=request, for_update=True)

            if not request.user.is_staff and purchase.created_by != request.user:
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()
            result = state_service.transition(purchase, state_service.PURCHASE)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This purchase order cannot be confirmed right now."
                )

            purchase.confirm()

            event = create_event(
                event_type=PurchaseEventType.PURCHASE_CONFIRMED,
                payload={
                    "purchase_id": purchase.pk,
                    "reference": purchase.reference,
                    "supplier_id": purchase.partner_id,
                    "status": purchase.status,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ProcurementException as e:
        return htmx_error(request, f"Procurement Error: {e}", detail_url)

    except ValueError as e:
        # Catches missing picking types or warehouse configuration issues
        return htmx_error(request, f"Warehouse Configuration Error: {e}", detail_url)

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)

    except (Http404, PermissionDenied):
        raise

    except Exception:
        logger.exception("Failed to confirm purchase order %s", purchase_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Purchase Order Confirmed Successfully",
        redirect_url=detail_url,
        target="#purchases-display",
    )

@login_required
def delete_purchase(request, purchase_id):

    detail_url = reverse("purchases:purchases_list")

    try:
        with transaction.atomic():
            purchase = load_purchase_order(purchase_id=purchase_id, request=request, for_update=True)

            if not request.user.is_staff and purchase.created_by != request.user:
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()
            if not state_service.can_delete(purchase):
                raise ValidationError("This purchase order can no longer be deleted.")

            purchase_pk, supplier_id, purchase_status = purchase.pk, purchase.partner_id, purchase.status
            purchase.delete()

            event = create_event(
                event_type=PurchaseEventType.PURCHASE_DELETED,
                payload={
                    "purchase_id": purchase_pk,
                    "supplier_id": supplier_id,
                    "status": purchase_status,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e, detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to delete purchase order %s", purchase_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Purchase Order Deleted Successfully",
        redirect_url=detail_url,
        target="#purchases-display",

    )

@login_required
def send_purchase(request, purchase_id):

    detail_url = reverse("purchases:purchase_create_or_detail", kwargs={"purchase_id": purchase_id})

    try:
        with transaction.atomic():
            purchase = load_purchase_order(purchase_id=purchase_id, request=request, for_update=True)

            if not request.user.is_staff and purchase.created_by != request.user:
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()
            result = state_service.transition(purchase, state_service.SENT)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This purchase order cannot be send right now."
                )

            purchase.save(update_fields=["status"])

            event = create_event(
                event_type=PurchaseEventType.PURCHASE_SENT,
                payload={
                    "purchase_id": purchase.pk,
                    "reference": purchase.reference,
                    "supplier_id": purchase.partner_id,
                    "status": purchase.status,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to send purchase order %s", purchase_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Purchase Order Sent Successfully",
        redirect_url=detail_url,
        target="#purchases-display",
    )

@login_required
def approve_purchase(request, purchase_id):

    detail_url = reverse("purchases:purchase_create_or_detail", kwargs={"purchase_id": purchase_id})

    try:
        with transaction.atomic():
            purchase = load_purchase_order(purchase_id=purchase_id, request=request, for_update=True)

            if not request.user.is_staff and purchase.created_by != request.user:
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()
            result = state_service.transition(purchase, state_service.TO_APPROVE)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This purchase order cannot be approved right now."
                )

            purchase.save(update_fields=["status"])

            event = create_event(
                event_type=PurchaseEventType.PURCHASE_CONFIRMED,
                payload={
                    "purchase_id": purchase.pk,
                    "reference": purchase.reference,
                    "supplier_id": purchase.partner_id,
                    "status": purchase.status,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to approve purchase order %s", purchase_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Purchase Order Waiting for Approval",
        redirect_url=detail_url,
        target="#purchases-display",
    )

@login_required
def cancel_purchase(request, purchase_id):
    detail_url = reverse(
        "purchases:purchase_create_or_detail",
        kwargs={"purchase_id": purchase_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock purchase
            purchase = load_purchase_order(
                purchase_id=purchase_id,
                request=request,
                for_update=True,
            )

            # 2. Ownership permission
            if (
                not request.user.is_staff
                and purchase.created_by != request.user
            ):
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = purchase.status

            # 4. Administrative authorization
            #
            # Normal users:
            #   SENT / TO_APPROVE
            #
            # Staff:
            #   SENT / TO_APPROVE / PURCHASE
            #
            if not request.user.is_staff:
                if previous_state not in (
                    state_service.SENT,
                    state_service.TO_APPROVE,
                ):
                    raise PermissionDenied(
                        "You are not allowed to cancel this purchase order."
                    )

            # 5. Lock active shipments
            active_shipments = (
                StockPicking.objects
                .select_for_update()
                .filter(purchase_order=purchase)
                .exclude(status="CANCELLED")
            )

            # 6. State service performs ALL business validation
            #
            # This checks:
            # - allowed state transition
            # - DONE protection
            # - receiving protection
            # - payment rules, if configured
            # - other cancellation rules
            result = state_service.transition(
                purchase,
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
                        or "This purchase order cannot be cancelled right now."
                    )

                raise ValidationError(
                    errors
                    or "This purchase order cannot be cancelled right now."
                )

            # transition() already changed:
            #
            # purchase.status = CANCELLED
            #
            previous_state = result.get(
                "old_state",
                previous_state,
            )

            # 7. Administrative cancellation of pending shipments
            #
            # Only staff are allowed to cancel a confirmed PURCHASE
            # order and therefore its outstanding shipments.
            #
            # can_cancel() has already established that no physical
            # receiving has occurred.
            if (
                    request.user.is_staff
                    and previous_state == state_service.PURCHASE
            ):
                for shipment in active_shipments:
                    shipment.cancel()

            # 8. Persist state
            purchase.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            # 9. Event
            event = create_event(
                event_type=PurchaseEventType.PURCHASE_CANCELLED,
                payload={
                    "purchase_id": purchase.pk,
                    "reference": purchase.reference,
                    "supplier_id": purchase.partner_id,
                    "previous_status": previous_state,
                    "new_status": state_service.CANCELLED,
                },
                user_id=request.user.pk,
                source=(
                    "htmx"
                    if request.headers.get("HX-Request")
                    else "web"
                ),
            )

            transaction.on_commit(
                lambda: dispatch(event)
            )

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

    except PermissionDenied as e:
        return htmx_error(
            request,
            str(e) or "You do not have permission to cancel this purchase order.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to cancel purchase order %s",
            purchase_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Purchase Order Cancelled Successfully",
        redirect_url=detail_url,
        target="#purchases-display",
    )

@login_required
def reset_purchase(request, purchase_id):
    detail_url = reverse(
        "purchases:purchase_create_or_detail",
        kwargs={"purchase_id": purchase_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock purchase
            purchase = load_purchase_order(
                purchase_id=purchase_id,
                request=request,
                for_update=True,
            )

            # 2. Ownership permission
            if (
                not request.user.is_staff
                and purchase.created_by != request.user
            ):
                raise PermissionDenied

            state_service = PurchaseOrdersStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = purchase.status

            # 4. Administrative authorization
            #
            # Normal users:
            #   SENT / TO_APPROVE
            #
            # Staff:
            #   SENT / TO_APPROVE / PURCHASE
            #
            if not request.user.is_staff:
                if previous_state not in (
                    state_service.SENT,
                    state_service.TO_APPROVE,
                ):
                    raise PermissionDenied(
                        "You are not allowed to reset this purchase order."
                    )

            # 5. Lock active shipments
            active_shipments = (
                StockPicking.objects
                .select_for_update()
                .filter(purchase_order=purchase)
                .exclude(status="CANCELLED")
            )

            # 6. State service performs ALL reset validation
            #
            # This checks:
            # - allowed transition
            # - payment allocations
            # - physical receiving
            # - other reset rules
            result = state_service.transition(
                purchase,
                state_service.DRAFT,
            )

            if not result.get("success"):
                errors = result.get("errors")

                if isinstance(errors, dict):
                    messages = []

                    for field_errors in errors.values():
                        messages.extend(field_errors)

                    raise ValidationError(
                        messages
                        or "This purchase order cannot be reset to draft right now."
                    )

                raise ValidationError(
                    errors
                    or "This purchase order cannot be reset to draft right now."
                )

            # transition() already changed:
            #
            # purchase.status = DRAFT
            #
            previous_state = result.get(
                "old_state",
                previous_state,
            )

            # 7. Administrative reset of pending shipments
            #
            # Only staff can unwind a confirmed PURCHASE order.
            #
            # can_reset_to_draft() has already established that
            # no physical receiving has occurred.
            if (
                    request.user.is_staff
                    and previous_state == state_service.PURCHASE
            ):
                for shipment in active_shipments:
                    shipment.cancel()

            # 8. Persist state
            purchase.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            # 9. Event
            event = create_event(
                event_type=PurchaseEventType.PURCHASE_RESET_TO_DRAFT,
                payload={
                    "purchase_id": purchase.pk,
                    "reference": purchase.reference,
                    "supplier_id": purchase.partner_id,
                    "previous_status": previous_state,
                    "new_status": state_service.DRAFT,
                },
                user_id=request.user.pk,
                source=(
                    "htmx"
                    if request.headers.get("HX-Request")
                    else "web"
                ),
            )

            transaction.on_commit(
                lambda: dispatch(event)
            )

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

    except PermissionDenied as e:
        return htmx_error(
            request,
            str(e) or "You do not have permission to reset this purchase order.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to reset purchase order %s to draft",
            purchase_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Purchase order reset successfully.",
        redirect_url=detail_url,
        target="#purchases-display",
    )
