from django.shortcuts import get_object_or_404

from inventory.models import Product


def load_product(product_id, request, for_update=False):
    """Loads account scoped to the request company."""
    queryset = Product.objects.filter(company= request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=product_id)
