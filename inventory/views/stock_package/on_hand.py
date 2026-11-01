from django.core.paginator import Paginator
from pygments.lexers import data
from django.db import transaction
from django.shortcuts import  render, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from unicodedata import category
from inventory.models import Product, StockLocation, Warehouse, ProductsCategory


@login_required
@transaction.atomic
def stock_info(request,product_id):
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    stock_quants = product.quants.all()


    context = {
               'product':product,
               'stock_quants':stock_quants,
               }
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_components/on_hand.html', context)

    return render(request, 'inventory/stock/stock_details.html', context)
