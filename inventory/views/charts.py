from datetime import timezone
from django.db.models import When, F
from collections import OrderedDict, defaultdict
import random
from pygments.lexers import data
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.db.models import DecimalField
from django.db.models import Q, Sum, Count,Case
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from inventory.models import StockMove



def stock_view_charts(request):
    now = timezone.now()
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # =========================================================
    # 1️⃣ BAR CHART – Best selling products (current month)
    # =========================================================
    bestselling_qs = (
        StockMove.objects
        .filter(
            status="COMPLETED",
            created_at__year=now.year,
            created_at__month=now.month,
            product__company=request.company
        )
        .values("product__name")
        .annotate(
            total_quantity=Sum(
                Case(
                    When(move_type="SALES", then=F("quantity")),
                    When(then=-F("quantity")),
                    output_field=DecimalField()
                )
            )
        )
        .filter(total_quantity__gt=0)
        .order_by("-total_quantity")[:10]
    )

    def random_color():
        return f"rgba({random.randint(0,255)}, {random.randint(0,255)}, {random.randint(0,255)}, 0.6)"

    bar_labels = [item["product__name"] for item in bestselling_qs]
    bar_data = [float(item["total_quantity"]) for item in bestselling_qs]
    bar_bg = [random_color() for _ in bar_data]
    bar_border = [c.replace("0.6", "1") for c in bar_bg]

    # =========================================================
    # 2️⃣ PIE CHART – Delivery status (current month)
    # =========================================================
    delivery_stats = (
        DeliveryOrder.objects
        .filter(created_at__gte=start_month, company=request.company)
        .aggregate(
            pending=Count("id", filter=Q(status="PENDING")),
            completed=Count("id", filter=Q(status="COMPLETED")),
            cancelled=Count("id", filter=Q(status="CANCELLED")),
        )
    )

    pie_labels = ["Pending", "Completed", "Cancelled"]
    pie_data = [
        delivery_stats["pending"],
        delivery_stats["completed"],
        delivery_stats["cancelled"],
    ]

    # =========================================================
    # 3️⃣ LINE CHART – Sales trend (last 12 months)
    # =========================================================
    movement_qs = (
        StockMove.objects
        .filter(
            status="COMPLETED",
            product__company=request.company,
        )
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(
            total_quantity=Sum(
                Case(
                    When(move_type="SALES", then=F("quantity")),
                    When(move_type="CUSTOMER RETURN", then=-F("quantity")),
                    output_field=DecimalField()
                )
            )
        )
        .order_by("month")
    )

    months_dict = OrderedDict()
    for i in range(11, -1, -1):
        month = (now - relativedelta(months=i)).replace(day=1)
        months_dict[month.strftime("%b %Y")] = 0

    for entry in movement_qs:
        key = entry["month"].strftime("%b %Y")
        if key in months_dict:
            months_dict[key] = float(entry["total_quantity"] or 0)

    line_labels = list(months_dict.keys())
    line_data = list(months_dict.values())

    # =========================================================
    # 4️⃣ APEX COLUMN – Top 5 products per month (last 12 months)
    # =========================================================
    top_products_qs = (
        StockMove.objects
        .filter(
            status="COMPLETED",
            move_type__in=["SALES", "CUSTOMER RETURN"],
            product__company=request.company,
        )
        .annotate(month=TruncMonth("created_at"))
        .values("month", "product__name")
        .annotate(
            total_quantity=Sum(
                Case(
                    When(move_type="SALES", then=F("quantity")),
                    When(move_type="CUSTOMER RETURN", then=-F("quantity")),
                    output_field=DecimalField()
                )
            )
        )
        .filter(total_quantity__gt=0)
        .order_by("month", "-total_quantity")
    )

    # Prepare months
    apex_months = OrderedDict()
    for i in range(11, -1, -1):
        m = (now - relativedelta(months=i)).replace(day=1)
        apex_months[m.strftime("%b %Y")] = {}

    # Group rows by month
    monthly_products = defaultdict(list)
    for row in top_products_qs:
        key = row["month"].strftime("%b %Y")
        if key in apex_months:
            monthly_products[key].append(row)

    # Keep only best 5 products per month
    for month, rows in monthly_products.items():
        for r in rows[:5]:
            apex_months[month][r["product__name"]] = float(r["total_quantity"])

    # Collect all unique products
    products = set()
    for data in apex_months.values():
        products.update(data.keys())

    # Build Apex series
    apex_series = []
    for product in products:
        apex_series.append({
            "name": product,
            "data": [apex_months[m].get(product, 0) for m in apex_months]
        })

    # =========================================================
    # 🔁 FINAL RESPONSE
    # =========================================================
    return JsonResponse({
        "bar_chart": {
            "labels": bar_labels,
            "data": bar_data,
            "background": bar_bg,
            "border": bar_border,
        },
        "pie_chart_series": {
            "labels": pie_labels,
            "series": pie_data,
        },
        "line_chart": {
            "labels": line_labels,
            "data": line_data,
        },
        "apex_top_products": {
            "months": list(apex_months.keys()),
            "series": apex_series
        }
    })








