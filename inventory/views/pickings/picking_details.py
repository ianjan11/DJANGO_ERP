from django.contrib import messages
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from core.events import dispatch
from core.utils import htmx_error, htmx_success
from inventory.events import InventoryEventType
from inventory.services.stock_Picking.picking_loader import load_picking
from sales.events.order_events import create_event
import logging
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from inventory.services.stock_Picking.picking_state_service import PickingStateService
from .picking import PICKING_LIST_URLS,PICKING_TYPE_MAPPING
from ...forms.stock_operation_form import StockPickingHeaderForm, StockMoveFormSet
from ...models import StockPickingType
from ...models.procurement_group import ProcurementException
from ...services.stock_Picking.picking_chain import chain_context
from ...services.stock_Picking.returns_service import get_returnable_lines
from ...services.stock_picking_document_service.core.picking_payload_builder import build_payload
from ...services.stock_Picking.picking_service import create_stock_picking
from ...services.stock_picking_document_service.picking_document_service import DocumentService
from ...services.stock_picking_document_service.presentation.picking_htmx_swap_service import UIResponseService

logger = logging.getLogger(__name__)


picking_state = PickingStateService()




def _build_context(request, picking):
    form_data = request.POST if request.method == "POST" else None

    header_form = StockPickingHeaderForm(
        form_data,
        company=request.company,
        instance=picking,
    )

    formset = StockMoveFormSet(
        form_data,
        instance=picking,
        prefix="items",
        form_kwargs={
            "company": request.company,
            "picking": picking,
            "picking_status": picking.status,
        },
    )

    backorder = picking.backorders.all()
    stock_moves = picking.moves.all().order_by("-created_at")

    paginator = Paginator(stock_moves, 10)
    lines = paginator.get_page(request.GET.get("page"))

    return_lines = get_returnable_lines(picking)


    return {
        "picking": picking,
        "backorder": backorder,
        "lines": lines,
        "return_lines" : return_lines,
        "formset": formset,
        "header_form": header_form,
        "flags": picking_state.get_flags(picking),
        **chain_context(picking),
    }

@login_required
def picking_create_or_detail_view(request, picking_id=None):
    if not picking_id:
        picking_type_key = request.GET.get("picking_type")

        if picking_type_key not in PICKING_TYPE_MAPPING:
            messages.error(request, "Invalid picking operation type.")
            return redirect("inventory:receipt_list")

        fallback_url = reverse(PICKING_LIST_URLS[picking_type_key])
        operation_code = PICKING_TYPE_MAPPING[picking_type_key]

        try:
            with transaction.atomic():
                picking_type = (
                    StockPickingType.objects
                    .select_related(
                        "warehouse",
                        "default_source_location",
                        "default_dest_location",
                    )
                    .filter(
                        warehouse__company=request.company,
                        active=True,
                        code=operation_code,
                    )
                    .first()
                )

                if not picking_type:
                    messages.error(
                        request,
                        "No active operation type is configured for this company.",
                    )
                    return redirect(fallback_url)

                picking = create_stock_picking(
                    request,
                    picking_type=picking_type,
                )

        except Exception:
            logger.exception(
                "Failed to create picking for type '%s'.",
                picking_type_key,
            )
            messages.error(
                request,
                "Failed to initialize  document. Please try again.",
            )
            return htmx_error(request, "Failed to initialize document. Please try again.")

        return redirect(
            "inventory:picking_detail",
            picking_id=picking.pk,
        )

    picking = load_picking(
        picking_id=picking_id,
        request=request,
    )

    context = _build_context(request, picking)

    template = (
        "inventory/pickings/partials/picking_details_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/pickings/picking_details.html"
    )

    return render(request, template, context)


@login_required
def picking_item_row(request, picking_id):

    picking = load_picking(picking_id, request)

    prefix = request.GET.get('prefix', 'items')
    total_forms = int(request.GET.get('total_forms', 0))

    form_data = request.POST if request.method == "POST" else None


    formset = StockMoveFormSet(
        form_data,
        instance=picking,
        prefix="items",
        form_kwargs={
            "company": request.company,
            "picking": picking,
            "picking_status": picking.status,
        },
    )

    form = formset.empty_form
    form.prefix = f"{prefix}-{total_forms}"

    html = render_to_string(
        'inventory/pickings/partials/item_row.html',
        {'form': form, 'picking':picking},
        request=request,
    )
    return HttpResponse(html)

@login_required
@require_POST
def picking_update(request):

    picking_id = request.POST.get("picking_id")


    if not picking_id:
        return HttpResponseBadRequest("Missing picking_id")

    picking = load_picking(picking_id, request, for_update=True)

    payload, dropped_unsaved_rows = build_payload(request.POST)


    # 2. HAND OFF TO ORCHESTRATOR
    try:
        context = DocumentService().apply_state(
            picking=picking,
            payload=payload,
            dropped_unsaved_rows=dropped_unsaved_rows,
            request=request,
        )
    except Exception:
        logger.exception("apply_state failed for picking_id=%s", picking_id)
        raise

    return UIResponseService().render(request=request, payload=context)


def _check(picking, action):
    """Ask the state service; raise ValidationError with its messages if not allowed."""
    result = picking_state.check(picking, action)
    if result.get("errors"):
        raise ValidationError(result["errors"])


@login_required
@require_POST
def confirm_picking_view(request, picking_id):
    """Draft -> confirmed. Does not reserve stock and does not move anything."""
    detail_url = reverse("inventory:picking_detail", kwargs={"picking_id": picking_id})

    try:
        with transaction.atomic():
            picking = load_picking(picking_id, request=request, for_update=True)
            _check(picking, "confirm")

            moves = picking.moves.all()
            if not moves:
                raise ValidationError("Please add at least one item before confirming this transfer.")

            picking.action_confirm()
            # No event on purpose: PICKING_CONFIRMED already means "completed" to your handlers.

    except Http404:
        raise
    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), detail_url)
    except ProcurementException as e:
        return htmx_error(request, str(e), detail_url)
    except Exception:
        logger.exception("Failed to confirm picking %s", picking_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Picking confirmed.",
        redirect_url=detail_url,
        target="#inventory-display",

    )


@login_required
@require_POST
def assign_picking_view(request, picking_id):
    """Reserve stock for the picking's moves. Reports what could not be reserved."""
    detail_url = reverse("inventory:picking_detail", kwargs={"picking_id": picking_id})

    try:
        with transaction.atomic():
            picking = load_picking(picking_id, request=request, for_update=True)
            _check(picking, "assign")

            shortages = picking.action_assign(allow_break=True)   # {move: shortage}
            shortage_names = [f"{m.product.name} (short {qty})" for m, qty in shortages.items()]

    except Http404:
        raise
    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), detail_url)
    except ProcurementException as e:
        return htmx_error(request, str(e), detail_url)
    except Exception:
        logger.exception("Failed to assign picking %s", picking_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    if shortage_names:
        message = "Reserved what was available. Not enough stock for: " + ", ".join(shortage_names) + "."
    else:
        message = "Stock reserved."

    return htmx_success(
        request,
        message=message,
        redirect_url=detail_url,
        target="#inventory-display",

    )


@login_required
@require_POST
def validate_picking_view(request, picking_id):
    """Complete the ready moves; whatever cannot complete goes on a backorder."""
    detail_url = reverse("inventory:picking_detail", kwargs={"picking_id": picking_id})

    try:
        with transaction.atomic():
            picking = load_picking(picking_id, request=request, for_update=True)
            _check(picking, "validate")

            backorder = picking.validate()

            event = create_event(
                event_type=InventoryEventType.PICKING_CONFIRMED,   # kept: your handlers expect it
                payload={
                    "picking_id": picking.pk,
                    "reference": picking.name,
                    "backorder_id": backorder.pk if backorder else None,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get("HX-Request") else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except Http404:
        raise
    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), detail_url)
    except ProcurementException as e:
        return htmx_error(request, str(e), detail_url)
    except Exception:
        logger.exception("Failed to validate picking %s", picking_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    if backorder:
        message = (
            f"Picking partially validated. Backorder {backorder.name} "
            "was created for items that could not be fulfilled."
        )
    else:
        message = "Picking validated successfully."

    return htmx_success(
        request,
        message=message,
        redirect_url=detail_url,
        target="#inventory-display",

    )


@login_required
@require_POST
def cancel_picking_view(request, picking_id):
    detail_url = reverse("inventory:picking_detail", kwargs={"picking_id": picking_id})

    try:
        with transaction.atomic():
            picking = load_picking(picking_id, request=request, for_update=True)
            _check(picking, "cancel")

            previous_status = picking.status
            picking.cancel()

            event = create_event(
                event_type=InventoryEventType.PICKING_CANCELLED,
                payload={
                    "picking_id": picking.pk,
                    "previous_status": previous_status,
                },
                user_id=request.user.pk,
            )
            transaction.on_commit(lambda: dispatch(event))

    except Http404:
        raise
    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), detail_url)
    except Exception:
        logger.exception("Failed to cancel picking %s", picking_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Picking cancelled successfully.",
        redirect_url=detail_url,
        target="#inventory-display",

    )



@login_required
def get_next_picking_view(request, picking_id):
    picking = load_picking(picking_id, request=request)

    next_picking = picking.next_pickings().filter(company=request.company).first()

    if next_picking is None:
        messages.info(request, "This is the last step of the transfer chain.")
        return redirect("inventory:picking_detail", picking_id=picking.pk)

    return redirect("inventory:picking_detail", picking_id=next_picking.pk)


@login_required
def get_previous_picking_view(request, picking_id):
    picking = load_picking(picking_id, request=request)
    prev = picking.previous_pickings().filter(company=request.company).first()
    if prev is None:
        messages.info(request, "This is the first step of the transfer chain.")
        return redirect("inventory:picking_detail", picking_id=picking.pk)
    return redirect("inventory:picking_detail", picking_id=prev.pk)


