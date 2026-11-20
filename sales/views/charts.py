from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum,
    Count,
    Q,
)
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils import timezone

from inventory.models import (
    StockLocation,
    StockMove,
    StockMoveLine,
)
from sales.models import SalesOrder


def _aware(d):
    """date -> timezone-aware datetime at 00:00 (avoids naive-datetime warnings)."""
    return timezone.make_aware(datetime.combine(d, time.min))


@login_required
def sales_view_charts(request):
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

    def _key(dt):
        return timezone.localtime(dt).strftime("%Y-%m") if timezone.is_aware(dt) else dt.strftime("%Y-%m")

    # Base Sales Orders in Date Range
    sales_orders = SalesOrder.objects.filter(
        company=company,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    # Confirmed or Done orders for revenue & volume charts
    confirmed_sales_orders = sales_orders.filter(
        status__in=['CONFIRMED', 'DONE']
    )

    # ---------------------------------------------------------
    # LINE CHART 1: MONTHLY SALES REVENUE (Last 12 Months)
    # ---------------------------------------------------------
    monthly_revenue = (
        confirmed_sales_orders
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount_total"))
        .order_by("month")
    )

    revenue_map = {_key(r["month"]): r["total"] or Decimal("0") for r in monthly_revenue}

    line_chart = {
        "labels": month_labels,
        "data": [float(revenue_map.get(m.strftime("%Y-%m"), Decimal("0"))) for m in months],
    }

    # ---------------------------------------------------------
    # LINE CHART 2: MONTHLY SALES ORDER VOLUME / COUNT
    # ---------------------------------------------------------
    monthly_volume = (
        confirmed_sales_orders
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )

    volume_map = {_key(r["month"]): r["total"] or 0 for r in monthly_volume}

    volume_line_chart = {
        "labels": month_labels,
        "data": [float(volume_map.get(m.strftime("%Y-%m"), 0)) for m in months],
    }

    # ---------------------------------------------------------
    # TOP 5 PRODUCTS PER MONTH (Column Chart Breakdown from StockMoveLines)
    # ---------------------------------------------------------
    movement_lines = StockMoveLine.objects.filter(
        move__product__company=company,
        move__status=StockMove.Status.COMPLETED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

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
    # ---------------------------------------------------------
    this_month_outgoing = outgoing_lines.filter(
        created_at__gte=_aware(current_month),
        created_at__lt=end_dt
    )

    this_month_sales = list(
        this_month_outgoing
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
    # TOP CUSTOMERS BY REVENUE
    # ---------------------------------------------------------
    top_customers_query = list(
        confirmed_sales_orders
        .values("partner__name")
        .annotate(total=Sum("amount_total"))
        .order_by("-total")[:5]
    )

    top_customers = {
        "labels": [r["partner__name"] or "Unknown Partner" for r in top_customers_query],
        "data": [float(r["total"] or 0) for r in top_customers_query],
    }

    # ---------------------------------------------------------
    # DONUT CHART PIPELINES (Matching SalesOrder STATUS Choices)
    # ---------------------------------------------------------
    def get_quotations_status():
        counts = sales_orders.aggregate(
            draft=Count("id", filter=Q(status='DRAFT')),
            sent=Count("id", filter=Q(status='SENT')),
            confirmed=Count("id", filter=Q(status='CONFIRMED')),
            cancelled=Count("id", filter=Q(status='CANCELLED')),
        )
        return {
            "labels": ["Quotation", "Quotation Sent", "Confirmed", "Cancelled"],
            "series": [
                counts["draft"],
                counts["sent"],
                counts["confirmed"],
                counts["cancelled"],
            ],
        }

    def get_sales_order_status():
        counts = sales_orders.aggregate(
            confirmed=Count("id", filter=Q(status='CONFIRMED')),
            done=Count("id", filter=Q(status='DONE')),
            cancelled=Count("id", filter=Q(status='CANCELLED')),
        )
        return {
            "labels": ["Sales Order", "Locked / Done", "Cancelled"],
            "series": [
                counts["confirmed"],
                counts["done"],
                counts["cancelled"],
            ],
        }

    def get_delivery_status_donut():
        counts = sales_orders.aggregate(
            not_delivered=Count("id", filter=Q(delivery_status='NOT_DELIVERED')),
            partial=Count("id", filter=Q(delivery_status='PARTIALLY_DELIVERED')),
            delivered=Count("id", filter=Q(delivery_status='DELIVERED')),
            cancelled=Count("id", filter=Q(delivery_status='CANCELLED')),
        )
        return {
            "labels": ["Not Delivered", "Partially Delivered", "Delivered", "Cancelled"],
            "series": [
                counts["not_delivered"],
                counts["partial"],
                counts["delivered"],
                counts["cancelled"],
            ],
        }

    def get_invoice_status_donut():
        counts = sales_orders.aggregate(
            no=Count("id", filter=Q(invoice_status="no")),
            to_invoice=Count("id", filter=Q(invoice_status="to_invoice")),
            invoiced=Count("id", filter=Q(invoice_status="invoiced")),
        )
        return {
            "labels": ["Nothing to Invoice", "To Invoice", "Fully Invoiced"],
            "series": [
                counts["no"],
                counts["to_invoice"],
                counts["invoiced"],
            ],
        }

    return JsonResponse({
        "line_chart": line_chart,
        "volume_line_chart": volume_line_chart,
        "apex_top_products": apex_top_products,
        "best_selling": best_selling,
        "least_selling": least_selling,
        "top_customers": top_customers,
        "pie_quotations": get_quotations_status(),
        "pie_sales": get_sales_order_status(),
        "pie_delivery": get_delivery_status_donut(),
        "pie_invoices": get_invoice_status_donut(),
    })