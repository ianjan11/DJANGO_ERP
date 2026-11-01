from django.core.paginator import Paginator
from pygments.lexers import data
from accounting.models import Journal
from core.models import Partner
from core.events import dispatch
from core.services.document_service.core.payload_builder import build_payload
from core.services.document_service.document_service import DocumentService
from core.services.document_service.presentation.htmx_swap_service import UIResponseService
from core.utils.extract_errors import extract_first_error
from inventory.models.procurement_group import ProcurementException
from sales.events import SalesEventType
from inventory.models import StockQuant, StockMove, StockLocation, StockPicking, Warehouse
from core.models import Currency
from sales.events.order_events import create_event
from django.urls import reverse
import logging
from django.http import Http404
from core.utils import htmx_error, htmx_success
from sales.services.sales_order_service.creator import create_sales_order
from sales.services.sales_order_service.saler_order_loader import load_sales_order
from django.contrib import messages
from django.template.loader import render_to_string
from pygments.lexers import data
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest
from sales.models import SalesOrderLine
from sales.forms import SalesOrderLineFormSet, SalesOrderForm
from django.core.exceptions import ValidationError, PermissionDenied
import json
from core.services.document_service.quant_service import  pre_resolve, resolve_warehouse
from sales.services.sales_order_service.sales_order_confirm import confirm_sales_order
from sales.services.sales_order_service.sales_order_state_service import SalesOrdersStateService

logger = logging.getLogger('sales.invoice')

def _build_context(request, order, header_form, formset):

    fulfillment_location = getattr(order, "fulfillment_location", None) if order else None

    if fulfillment_location and fulfillment_location.view_location:
        location_ids = StockLocation.objects.filter(
            parent_path__startswith=fulfillment_location.view_location.parent_path
        ).values_list("id", flat=True)

        quants = StockQuant.objects.filter(
            location_id__in=location_ids
        ).select_related("product", "location")
    else:
        quants = StockQuant.objects.none()
    items = (
        SalesOrderLine.objects.filter(sales_order=order)
        .select_related('product')
        .order_by('-id')
        if order
        else SalesOrderLine.objects.none()
    )
    paginator = Paginator(items, 10)
    page_obj = paginator.get_page(request.GET.get('page'))




    return {
        'order': order,
        'header_form': header_form,
        'formset': formset,
        'quant': quants,
        'items': page_obj,
        'partners': Partner.objects.filter(is_active=True),
        'journals': Journal.objects.filter(
            company=request.company,
            type__in=['CASH', 'BANK'],
        ),
        'currencies': Currency.objects.all(),
        'is_new': order is None,
        'partner_type': 'customer',
    }


def sales_order_item_row(request, order_id):
    order = load_sales_order(order_id=order_id, request=request)

    partner_id = order.partner_id

    if not partner_id:
        return htmx_error(request, "Please Select a Partner first and try again.")

    prefix = request.GET.get('prefix', 'items')
    total_forms = int(request.GET.get('total_forms', 0))

    formset = SalesOrderLineFormSet(
        instance=order,
        prefix=prefix,
        form_kwargs={"doc": order},

    )

    form = formset.empty_form
    form.prefix = f"{prefix}-{total_forms}"

    html = render_to_string(
        'sales/partials/order_item_row.html',
        {'form': form, 'order': order},
        request=request,
    )
    return HttpResponse(html)

@login_required
def sales_order_update(request):

    if request.method != "POST":
        return HttpResponse(status=405)

    order_id = request.POST.get("order_id")

    if not order_id:
        return HttpResponseBadRequest("Missing order_id")

    order = load_sales_order(
        order_id=order_id, request=request,for_update=True
    )

    try:
        payload, dropped_unsaved_rows = build_payload(request.POST, doc_type="sales_order")

        warehouse = (
            order.fulfillment_location
            if isinstance(order.fulfillment_location, Warehouse)
            else resolve_warehouse(order.fulfillment_location)
        )

        payload = pre_resolve(payload, warehouse)


    except ValidationError as e:
        return htmx_error(
            message=e.message,
            request=request,
        )


    logger.info(payload)


        # 2. HAND OFF TO ORCHESTRATOR
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

def sales_order_totals(request, order_id):

    order = load_sales_order(
        order_id=order_id, request=request
    )
    return render(request, 'sales/partials/order_totals.html', {'order': order})

def refresh_order(request, order_id):

    order = load_sales_order(
        order_id=order_id, request=request
    )

    header_form = SalesOrderForm(
        request.POST or None,
        instance=order,
    )

    formset = SalesOrderLineFormSet(
        request.POST or None,
        instance=order,
        prefix="items",
        form_kwargs={"doc": order},

    )

    context = _build_context(
        request=request,
        order=order,
        header_form=header_form,
        formset=formset,
    )


    if request.headers.get('HX-Request'):
        return render(request, 'sales/partials/order_form_partial.html',context)

    return render(request, 'sales/partials/order_form_partial.html',context)

@login_required
def sales_order_create_or_detail(request, order_id=None):

    # ─────────────────────────────────────
    # CREATE FLOW
    # ─────────────────────────────────────
    if not order_id:
        try:
            with transaction.atomic():
                order = create_sales_order(request)

                event = create_event(
                    event_type=SalesEventType.ORDER_CREATED,
                    user_id=request.user.id,
                    source="htmx" if request.headers.get('HX-Request') else "web",
                    payload={
                        "order_id": order.id,

                    }
                )

                transaction.on_commit(lambda: dispatch(event))

        except Exception as e:
            logger.exception("Failed to create sales order: %s", e)
            messages.error(request, "Something went wrong. Please try again.")
            return htmx_error(request,"Failed to initialize draft document. Please try again.")

        return redirect("sales:sales_order_create_or_detail", order_id=order.id)

    # ─────────────────────────────────────
    # LOAD FLOW
    # ─────────────────────────────────────
    order = load_sales_order(order_id, request)

    header_form = SalesOrderForm(
        request.POST or None,
        instance=order,
        company=order.company,
    )

    formset = SalesOrderLineFormSet(
        request.POST or None,
        instance=order,
        prefix="items",
        form_kwargs={"doc": order},

    )

    context = _build_context(
        request=request,
        order=order,
        header_form=header_form,
        formset=formset,
    )

    if request.headers.get("HX-Request"):
        return render(request, "sales/partials/order_detail_partial.html", context)

    return render(request, "sales/order_detail.html", context)

@login_required
def send_order_view(request, order_id):
    detail_url = reverse(
        "sales:sales_order_create_or_detail",
        kwargs={"order_id": order_id}
    )

    try:
        with transaction.atomic():
            order = load_sales_order(order_id, request, for_update=True)

            if not request.user.is_staff and order.created_by != request.user:
                raise PermissionDenied

            state_service = SalesOrdersStateService()
            result = state_service.transition(order, state_service.SENT)

            if not result.get("success"):
                errors = result.get("errors", {})
                message = extract_first_error(
                    errors,
                    "This sales order cannot be sent right now."
                )
                raise ValidationError(message)

            order.save(update_fields=["status"])

            event = create_event(
                event_type=SalesEventType.ORDER_SENT,
                payload={
                    "order_id": order.pk,
                    "order_number": order.order_number,
                    "partner_id": order.partner_id,
                    "status": order.status,
                },
                user_id=request.user.pk,
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, str(e), detail_url)

    except (Http404, PermissionDenied):
        raise

    except Exception:
        logger.exception("Failed to send sales order %s", order_id)
        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url
        )

    return htmx_success(
        request,
        message="Sales Order Sent Successfully",
        redirect_url=detail_url,
        target="#sales-display",
    )

@login_required
def delete_order_view(request, order_id):

    detail_url = reverse("sales:sales_orders_list")

    try:
        with transaction.atomic():
            order = load_sales_order(order_id=order_id, request=request, for_update=True)

            if not request.user.is_staff and order.created_by != request.user:
                raise PermissionDenied

            state_service = SalesOrdersStateService()
            if not state_service.can_delete(order):
                raise ValidationError("This sales order can no longer be deleted.")

            order_pk, partner_id, order_status = order.pk, order.partner_id, order.status
            order.delete()

            event = create_event(
                event_type=SalesEventType.ORDER_DELETED,
                payload={
                    "order_id": order_pk,
                    "partner_id": partner_id,
                    "status": order_status,
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
        logger.exception("Failed to delete sales order %s", order_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Sales Order Deleted Successfully",
        redirect_url=detail_url,
        target="#sales-display",

    )

@login_required
def confirm_order_view(request, order_id):

    detail_url = reverse("sales:sales_order_create_or_detail", kwargs={"order_id": order_id})

    try:
        with transaction.atomic():
            order = load_sales_order(order_id=order_id, request=request, for_update=True)

            if not request.user.is_staff and order.created_by != request.user:
                raise PermissionDenied

            state_service = SalesOrdersStateService()
            result = state_service.transition(order, state_service.CONFIRMED)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This sales order cannot be confirmed right now."
                )

            confirm_sales_order(order)

            event = create_event(
                event_type=SalesEventType.ORDER_CONFIRMED,
                payload={
                    "order_id": order.pk,
                    "order_number": order.order_number,
                    "partner_id": order.partner_id,
                    "status": order.status,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ProcurementException as e:
        return htmx_error(request, f"Procurement Error: {e}", detail_url)

    except ValueError as e:
        # Handles uninitialized warehouse picking types / routes cleanly
        return htmx_error(request, f"Warehouse Configuration Error: {e}", detail_url)

    except ValidationError as e:
        # e.message_dict or e.message will automatically be parsed by htmx_error!
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)

    except (Http404, PermissionDenied):
        raise

    except Exception:
        logger.exception("Failed to confirm sales order %s", order_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Sales Order Confirmed Successfully",
        redirect_url=detail_url,
        target="#sales-display",
    )

@login_required
def cancel_order_view(request, order_id):

    detail_url = reverse(
        "sales:sales_order_create_or_detail",
        kwargs={"order_id": order_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock the sales order
            order = load_sales_order(
                order_id=order_id,
                request=request,
                for_update=True,
            )

            # 2. Basic ownership permission
            if (
                not request.user.is_staff
                and order.created_by != request.user
            ):
                raise PermissionDenied

            state_service = SalesOrdersStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = order.status

            # 4. Authorization based on ORIGINAL state
            #
            # Normal users may cancel:
            #   DRAFT
            #   SENT
            #
            # Staff may also cancel:
            #   CONFIRMED
            #
            if not request.user.is_staff:
                if previous_state not in (
                    state_service.DRAFT,
                    state_service.SENT,
                ):
                    raise PermissionDenied(
                        "You are not allowed to cancel this sales order."
                    )

            # 5. Lock active deliveries
            active_deliveries = (
                StockPicking.objects
                .select_for_update()
                .filter(sales_order=order)
                .exclude(status=StockPicking.Status.CANCELLED)
            )

            # 6. Let the state service perform ALL
            # cancellation business validation.
            result = state_service.transition(
                order,
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
                        or "This sales order cannot be cancelled right now."
                    )

                raise ValidationError(
                    errors
                    or "This sales order cannot be cancelled right now."
                )

            # 7. Only staff cancelling a CONFIRMED order
            # needs to cancel its outstanding deliveries.
            #
            # can_cancel() has already established that no
            # PARTIAL/COMPLETED delivery exists.
            if (
                request.user.is_staff
                and previous_state == state_service.CONFIRMED
            ):
                for delivery in active_deliveries:
                    delivery.cancel()

            # 8. Persist state
            #
            # transition() already changed:
            #
            # order.status = CANCELLED
            #
            order.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            # 9. Event
            event = create_event(
                event_type=SalesEventType.ORDER_CANCELLED,
                payload={
                    "order_id": order.pk,
                    "order_number": order.order_number,
                    "partner_id": order.partner_id,
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

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to cancel this sales order.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to cancel sales order %s",
            order_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Sales Order Cancelled Successfully",
        redirect_url=detail_url,
        target="#sales-display",
    )

@login_required
def reset_order_view(request, order_id):
    detail_url = reverse(
        "sales:sales_order_create_or_detail",
        kwargs={"order_id": order_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock the sales order
            order = load_sales_order(
                order_id=order_id,
                request=request,
                for_update=True,
            )

            # 2. Basic ownership permission
            if (
                not request.user.is_staff
                and order.created_by != request.user
            ):
                raise PermissionDenied

            state_service = SalesOrdersStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = order.status

            # 4. Authorization based on ORIGINAL state
            #
            # Normal users may reset SENT -> DRAFT.
            #
            # Staff may also reset CONFIRMED -> DRAFT.
            #
            if not request.user.is_staff:
                if previous_state not in (
                    state_service.SENT,
                ):
                    raise PermissionDenied(
                        "You are not allowed to reset this sales order."
                    )

            # 5. Lock active deliveries
            active_deliveries = (
                StockPicking.objects
                .select_for_update()
                .filter(sales_order=order)
                .exclude(status=StockPicking.Status.CANCELLED)
            )

            # 6. Let the state service perform ALL
            # reset-to-draft business validation.
            result = state_service.transition(
                order,
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
                        or "This sales order cannot be reset to draft right now."
                    )

                raise ValidationError(
                    errors
                    or "This sales order cannot be reset to draft right now."
                )

            # 7. Staff resetting CONFIRMED -> DRAFT
            # must cancel outstanding deliveries.
            #
            # can_reset_to_draft() has already established that
            # there is no partial/completed delivery.
            if (
                request.user.is_staff
                and previous_state == state_service.CONFIRMED
            ):
                for delivery in active_deliveries:
                    delivery.cancel()

            # 8. Persist state
            #
            # transition() already changed:
            #
            # order.status = DRAFT
            #
            order.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            # 9. Event
            event = create_event(
                event_type=SalesEventType.ORDER_RESET_TO_DRAFT,
                payload={
                    "order_id": order.pk,
                    "order_number": order.order_number,
                    "partner_id": order.partner_id,
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

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to reset this sales order.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to reset sales order %s to draft",
            order_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Sales order reset successfully.",
        redirect_url=detail_url,
        target="#sales-display",
    )


