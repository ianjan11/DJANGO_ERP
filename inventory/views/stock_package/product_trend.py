from datetime import timezone
from django.db.models import When, F
from collections import OrderedDict, defaultdict
import random

from django.shortcuts import get_object_or_404, render
from pygments.lexers import data
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.db.models import DecimalField
from django.db.models import Q, Sum, Count,Case
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from inventory.models import StockMove, Product


def product_movement_trend(request, product_id):
    product = get_object_or_404(Product, id=product_id)


    context = {
        'product': product,
    }
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_components/trend.html', context)

    return render(request, 'inventory/stock/stock_details.html', context)






def product_movement_chart_per_month(request, product_id):
    location_id = request.GET.get("location_id")
    warehouse_id = request.GET.get("warehouse_id")
    now = timezone.now()
    year = now.year

    qs = StockMove.objects.filter(
        product_id=product_id,
        status__in=["PENDING", "COMPLETED"],
        created_at__year=year

    )

    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if location_id:
        qs = qs.filter(source_location_id=location_id)

    movement_qs = (
        qs.annotate(month=TruncMonth('created_at'))
        .values("month")
        .annotate(
            total_quantity=Sum(
                Case(
                    When( then=F("quantity")),
                    When(then=-F("quantity")),
                    output_field=DecimalField()
                )
            )
        )
        .order_by('month')
    )

    months_dict = OrderedDict()
    for i in range(11, -1, -1):
        month = (now - relativedelta(months=i)).replace(day=1)
        months_dict[month.strftime("%b %Y")] = 0

    for entry in movement_qs:
        months_dict[entry["month"].strftime("%b %Y")] = float(
            entry["total_quantity"] or 0
        )

    return JsonResponse({
        "months": list(months_dict.keys()),
        "quantities": list(months_dict.values())
    })
