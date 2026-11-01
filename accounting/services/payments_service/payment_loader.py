from django.shortcuts import get_object_or_404

from accounting.models import Payment
from sales.models import SalesOrder


def load_payment(payment_id, request, for_update=False):
    """Loads a payment scoped to the user's company."""
    queryset = Payment.objects.filter(company=request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=payment_id)
