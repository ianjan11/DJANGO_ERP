from django.shortcuts import get_object_or_404
from sales.models import SalesOrder


def load_sales_order(order_id, request, for_update=False):
    """Loads a sales order scoped to the user's company."""
    queryset = SalesOrder.objects.filter(company=request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=order_id)
