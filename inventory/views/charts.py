from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum,
    Count,
    Case,
    When,
    F,
    Value,
    DecimalField,
    Q,
)
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils import timezone

from inventory.models import (
    StockLocation,
    StockMove,
    StockMoveLine,
    StockPicking,
    StockPickingType,
)


def _aware(d):
    """date -> timezone-aware datetime at 00:00 (avoids naive-datetime warnings)."""
    return timezone.make_aware(datetime.combine(d, time.min))


@login_required
def stock_view_charts(request):
    company = request.company
    today = timezone.localdate()

    INTERNAL = StockLocation.Usage.INTERNAL
    CUSTOMER = StockLocation.Usage.CUSTOMER

    # ---------------------------------------------------------
    # DATE RANGE: LAST 12 MONTHS
    # ---------------------------------------------------------
    current_month = today.replace(day=1)
    start_month = current_month - relativedelta(months=11)
    end_month = current_month + relativedelta(months=1)

    start_dt = _aware(start_month)
    end_dt = _aware(end_month)

    months = [start_month + relativedelta(months=i) for i in range(12)]
    month_labels = [m.strftime("%b %Y") for m in months]

    # ---------------------------------------------------------
    # BASE EXECUTED STOCK MOVEMENTS
    # ---------------------------------------------------------
    movement_lines = StockMoveLine.objects.filter(
        move__product__company=company,
        move__status=StockMove.Status.COMPLETED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    # ---------------------------------------------------------
    # LINE CHART: MONTHLY NET SALES (out = +, customer return = -)
    # ---------------------------------------------------------
    net_quantity = Case(
        When(source_location__usage=INTERNAL, dest_location__usage=CUSTOMER,
             then=F("quantity")),
        When(source_location__usage=CUSTOMER, dest_location__usage=INTERNAL,
             then=-F("quantity")),
        default=Value(0),
        output_field=DecimalField(max_digits=20, decimal_places=6),
    )

    monthly_sales = (
        movement_lines
        .annotate(month=TruncMonth("created_at"), net_quantity=net_quantity)
        .values("month")
        .annotate(total=Sum("net_quantity"))
        .order_by("month")
    )

    # TruncMonth returns an aware datetime; localise before formatting the key.
    def _key(dt):
        return timezone.localtime(dt).strftime("%Y-%m") if timezone.is_aware(dt) else dt.strftime("%Y-%m")

    monthly_sales_map = {_key(r["month"]): r["total"] or Decimal("0") for r in monthly_sales}

    line_chart = {
        "labels": month_labels,
        "data": [float(monthly_sales_map.get(m.strftime("%Y-%m"), Decimal("0"))) for m in months],
    }

    # ---------------------------------------------------------
    # TOP 5 PRODUCTS PER MONTH (outgoing only)
    # ---------------------------------------------------------
    outgoing_lines = movement_lines.filter(
        source_location__usage=INTERNAL,
        dest_location__usage=CUSTOMER,
    )

    top_products = (
        outgoing_lines
        .values("move__product__name")
        .annotate(total_quantity=Sum("quantity"))
        .order_by("-total_quantity")[:5]
    )
    top_product_names = [r["move__product__name"] for r in top_products]

    product_monthly_data = (
        outgoing_lines
        .filter(move__product__name__in=top_product_names)
        .annotate(month=TruncMonth("created_at"))
        .values("move__product__name", "month")
        .annotate(total=Sum("quantity"))
        .order_by("month")
    )

    product_data_map = defaultdict(dict)
    for row in product_monthly_data:
        product_data_map[row["move__product__name"]][_key(row["month"])] = row["total"] or Decimal("0")

    apex_series = [
        {
            "name": name,
            "data": [
                float(product_data_map.get(name, {}).get(m.strftime("%Y-%m"), Decimal("0")))
                for m in months
            ],
        }
        for name in top_product_names
    ]

    apex_top_products = {"months": month_labels, "series": apex_series}

    # ---------------------------------------------------------
    # BEST / LEAST SELLING — CURRENT MONTH
    # Only products that actually sold this month are ranked.
    # ---------------------------------------------------------
    this_month_sales = list(
        outgoing_lines
        .filter(created_at__gte=_aware(current_month), created_at__lt=end_dt)
        .values("move__product__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")
    )

    def _ranking(rows):
        return {
            "labels": [r["move__product__name"] for r in rows],
            "data": [float(r["total"] or 0) for r in rows],
        }

    best_selling = _ranking(this_month_sales[:5])
    least_selling = _ranking(sorted(this_month_sales, key=lambda r: r["total"])[:5])

    # ---------------------------------------------------------
    # PICKING STATUS HELPER
    # Pending = draft + waiting + confirmed | Ready = assigned
    # ---------------------------------------------------------
    def get_picking_status(code):
        counts = StockPicking.objects.filter(
            company=company,
            picking_type__code=code,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        ).aggregate(
            draft=Count("id", filter=Q(status=StockPicking.Status.DRAFT)),
            waiting=Count("id", filter=Q(status=StockPicking.Status.WAITING)),
            confirmed=Count("id", filter=Q(status=StockPicking.Status.CONFIRMED)),
            assigned=Count("id", filter=Q(status=StockPicking.Status.ASSIGNED)),
            completed=Count("id", filter=Q(status=StockPicking.Status.COMPLETED)),
            cancelled=Count("id", filter=Q(status=StockPicking.Status.CANCELLED)),
        )
        return {
            "labels": ["Pending", "Ready", "Completed", "Cancelled"],
            "series": [
                counts["draft"] + counts["waiting"] + counts["confirmed"],
                counts["assigned"],
                counts["completed"],
                counts["cancelled"],
            ],
        }

    return JsonResponse({
        "line_chart": line_chart,
        "apex_top_products": apex_top_products,
        "best_selling": best_selling,
        "least_selling": least_selling,
        "pie_delivery": get_picking_status(StockPickingType.Code.OUTGOING),
        "pie_receipts": get_picking_status(StockPickingType.Code.INCOMING),
        "pie_transfers": get_picking_status(StockPickingType.Code.INTERNAL),
        "pie_returns": get_picking_status(StockPickingType.Code.RETURN),
    })