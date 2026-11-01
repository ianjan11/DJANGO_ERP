from django.shortcuts import get_object_or_404
from accounting.models import  Tax


def load_tax(tax_id, request, for_update=False):
    """Loads a payment scoped to the user's company."""
    queryset = Tax.objects.filter(company=request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=tax_id)
