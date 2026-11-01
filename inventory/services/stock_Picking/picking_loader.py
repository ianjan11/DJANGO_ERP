from django.shortcuts import get_object_or_404

from inventory.models import StockPicking, StockQuant


def load_picking(picking_id, request, for_update=False):
    """Loads a delivery order scoped to the user's company."""
    queryset = StockPicking.objects.filter(
        company=request.company
    )

    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=picking_id)



def load_quant(quant_id, request, for_update=False):
    """Loads a delivery order scoped to the user's company."""
    queryset = StockQuant.objects.filter(
        company=request.company
    )

    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=quant_id)