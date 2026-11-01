from django.shortcuts import get_object_or_404

from purchases.models import PurchaseOrder
from sales.models import SalesOrder


def load_purchase_order(purchase_id, request, for_update=False):
    """Loads a sales order scoped to the user's company."""
    queryset = PurchaseOrder.objects.filter(company=request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=purchase_id)
