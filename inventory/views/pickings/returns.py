import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.utils import htmx_error, htmx_success
from inventory.services.stock_Picking.picking_loader import load_picking
from inventory.services.stock_Picking.returns_service import create_return_from_picking

logger = logging.getLogger("sales.invoice")

QTY_PREFIX = "return_qty_"   # form fields: return_qty_<stock_move_id> = quantity


def _parse_return_lines(post):
    """Blank / zero quantities mean 'not returning this line'."""
    lines, errors = [], []
    for key, raw in post.items():
        if not key.startswith(QTY_PREFIX):
            continue
        raw = (raw or "").strip()
        if not raw:
            continue
        move_id = key[len(QTY_PREFIX):]
        try:
            qty = Decimal(raw)
            if not move_id.isdigit() or qty < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors.append(f"Invalid return quantity for move {move_id}.")
            continue
        if qty == 0:
            continue
        lines.append({"move_id": int(move_id), "quantity": qty})
    return lines, errors


@require_POST
@login_required
def issue_return_view(request, picking_id):
    detail_url = reverse("inventory:picking_detail",
                         kwargs={"picking_id": picking_id})

    lines_data, errors = _parse_return_lines(request.POST)
    if errors:
        return htmx_error(request, " ".join(errors), detail_url)
    if not lines_data:
        return htmx_error(request, "Enter a return quantity for at least one line.", detail_url)

    try:
        with transaction.atomic():
            picking = load_picking(picking_id, request, for_update=True)
            return_picking = create_return_from_picking(picking, lines_data, request.user)

    except ValidationError as e:
        return htmx_error(request, "; ".join(e.messages), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to create return for picking %s", picking_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message=f"Return {return_picking.name} created. Validate it to complete the return.",
        redirect_url= detail_url,
        target="#Inventory-display",
    )