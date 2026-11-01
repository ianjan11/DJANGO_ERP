from django.core.paginator import Paginator
from django.db.models import Q
from pygments.lexers import data
from django.db import transaction
from django.shortcuts import  render, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required

from inventory.forms import ProductForm
from inventory.models import Product, StockLocation, Warehouse, ProductsCategory
from django.db.models import Sum, Q, DecimalField, Value
from django.db.models.functions import Coalesce
from decimal import Decimal

@login_required
def stock_view(request):

    products = Product.objects.all().filter(company=request.company).order_by('-name')
    category_choices = ProductsCategory.objects.all().filter(company=request.company)


    search_product = request.GET.get('product_search')

    if search_product:
        products = products.filter(
            Q (name__icontains=search_product) |
            Q(sku__icontains=search_product)
        )


    product_category = request.GET.get('product_category')

    if product_category:
        products = products.filter(
            category__name__icontains=product_category
        )

    products = products.annotate(
        computed_stock=Coalesce(
            Sum('quants__quantity', filter=Q(quants__location__usage='internal')),
            Value(Decimal('0')),
            output_field=DecimalField()
        )
    )

    # 2. Now you can safely filter using the annotation name!
    stock_status = request.GET.get('stock_status')

    if stock_status == 'out':
        products = products.filter(computed_stock__lte=0)

    elif stock_status == 'ok':
        products = products.filter(computed_stock__gte=50)

    elif stock_status == 'low':
        products = products.filter(computed_stock__lte=50, computed_stock__gt=0)



    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)


    context = {
        'products': page_obj,
        'category_choices': category_choices,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_view_partial.html', context)


    return render(request, 'inventory/stock/stock_view.html', context)



