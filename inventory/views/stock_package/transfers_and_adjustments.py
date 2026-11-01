import logging
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.utils import htmx_error, htmx_success
from inventory.forms import PhysicalAdjustmentForm, StockRelocateForm
from inventory.services.adjustments_and_transfers.adjust_or_transfers_service import transfer_stock, adjust_stock

from inventory.services.stock_Picking.picking_loader import load_quant

logger = logging.getLogger(__name__)



@login_required
@require_POST
def stock_relocate_view(request):
    """Batch View: Relocates 100% of stock across all selected quant IDs."""
    redirect_url = reverse("inventory:physical_inventory")

    # 1. Extract selected quant IDs from request body
    quant_ids = request.POST.getlist("quant_ids")
    if not quant_ids:
        return htmx_error(request, "No stock items selected for relocation.", redirect_url)


    # 2. Validate form choices against company
    form = StockRelocateForm(request.POST, company=request.company)
    if not form.is_valid():
        error_msg = next(iter(form.errors.values()))[0]
        return htmx_error(request, error_msg, redirect_url)

    dest_loc = form.cleaned_data["destination_location"]
    reason = form.cleaned_data["reason"]

    # 3. Execute batch relocation inside an atomic transaction
    try:
        with transaction.atomic():
            relocated_count = 0

            for q_id in quant_ids:
                # Lock each target quant row for update
                locked_quant = load_quant(q_id, request=request, for_update=True)

                # Skip or raise if quant is already at the destination location
                if locked_quant.location_id == dest_loc.id:
                    continue

                transfer_stock(
                    source_quant=locked_quant,
                    quantity=locked_quant.quantity,
                    source_location=locked_quant.location,
                    destination_location=dest_loc,
                    user=request.user,
                    reason=reason,
                )
                relocated_count += 1

            if relocated_count == 0:
                return htmx_error(
                    request,
                    "Selected item(s) are already at the destination location.",
                    redirect_url,
                )

    except ValidationError as e:
        messages_text = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
        return htmx_error(request, messages_text, redirect_url)

    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed batch relocation for quant IDs: %s", quant_ids)
        return htmx_error(
            request,
            "Something went wrong while relocating stock. Please try again.",
            redirect_url,
        )

    return htmx_success(
        request,
        message=f"Successfully relocated {relocated_count} stock item(s).",
        redirect_url=redirect_url,
        target="#inventory-display",
    )


@login_required
@require_POST
def stock_adjust_view(request, quant_id):
    """Handles physical count adjustments against virtual locations."""
    redirect_url = reverse("inventory:physical_inventory")

    # 1. Validate form inputs first
    form = PhysicalAdjustmentForm(request.POST)
    if not form.is_valid():
        error_msg = next(iter(form.errors.values()))[0]
        return htmx_error(request, error_msg, redirect_url)

    counted_qty = form.cleaned_data["counted_quantity"]
    reason = form.cleaned_data["reason"]
    expected_quantity = form.cleaned_data["expected_quantity"]

    # 2. Execute atomic physical inventory adjustment
    try:
        with transaction.atomic():
            # Lock target quant for updating
            quant = load_quant(quant_id, request=request, for_update=True)

            picking = adjust_stock(
                quant=quant,
                counted_quantity=counted_qty,
                user=request.user,
                reason=reason,
                expected_quantity=expected_quantity,
            )

            if picking is None:
                return htmx_success(request, message="No difference. Stock unchanged.",
                                    redirect_url=redirect_url, target="#inventory-display")

    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), redirect_url)

    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to adjust stock for quant ID %s", quant_id)
        return htmx_error(
            request,
            "Something went wrong while adjusting stock. Please try again.",
            redirect_url,
        )

    return htmx_success(
        request,
        message="Stock adjusted Successfully",
        redirect_url=redirect_url,
        target="#inventory-display",
    )