import logging
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from inventory.models import StockMoveLine, StockPicking

logger = logging.getLogger(__name__)


def _build_context(request, picking, lines_queryset):
    # Search filter across operational lines
    search_lines = request.GET.get("search_lines")
    if search_lines:
        lines_queryset = lines_queryset.filter(
            Q(product__name__icontains=search_lines)
            | Q(dest_location__name__icontains=search_lines)
            | Q(source_location__name__icontains=search_lines)
            | Q(lot__name__icontains=search_lines)
        )

    # Paginate physical move lines directly
    paginator = Paginator(lines_queryset, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return {
        "picking": picking,
        "lines": page_obj,
    }


@login_required
@require_GET
def stock_move_operations(request, picking_id):
    """
    Renders line-level physical stock operations (bin allocations, lot numbers, quantity done)
    for all moves within a given StockPicking header.
    """
    picking = get_object_or_404(
        StockPicking.objects.filter(company=request.company),
        pk=picking_id
    )

    # Directly query all MoveLines belonging to any Move in this Picking
    lines_queryset = (
        StockMoveLine.objects.filter(
            move__picking=picking,
        )
        .select_related(
            "product",
            "source_location",       # Source bin
            "dest_location",  # Destination bin
            "lot",
            "product_uom",
            "move",
        )
        .order_by("-created_at",)
    )

    context = _build_context(request, picking, lines_queryset)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "inventory/move_operations/partials/move_operations_partial.html",
            context,
        )

    return render(
        request,
        "inventory/move_operations/move_operations.html",
        context,
    )