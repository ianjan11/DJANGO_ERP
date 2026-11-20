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
from purchases.models import PurchaseOrder


def _aware(d):
    """date -> timezone-aware datetime at 00:00 (avoids naive-datetime warnings)."""
    return timezone.make_aware(datetime.combine(d, time.min))


@login_required
def purchases_view_charts(request):
    company = request.company
    today = timezone.localdate()

    SUPPLIER = StockLocation.Usage.SUPPLIER
    INTERNAL = StockLocation.Usage.INTERNAL

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

    # Base Purchase Orders in Date Range
    purchase_orders = PurchaseOrder.objects.filter(
        company=company,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    # Confirmed or Done purchase orders for spend & volume charts
    confirmed_purchase_orders = purchase_orders.filter(
        status__in=['PURCHASE', 'DONE']
    )

    # ---------------------------------------------------------
    # LINE CHART 1: MONTHLY PURCHASE SPEND (Last 12 Months)
    # ---------------------------------------------------------
    monthly_spend = (
        confirmed_purchase_orders
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount_total"))
        .order_by("month")
    )

    spend_map = {_key(r["month"]): r["total"] or Decimal("0") for r in monthly_spend}

    line_chart = {
        "labels": month_labels,
        "data": [float(spend_map.get(m.strftime("%Y-%m"), Decimal("0"))) for m in months],
    }

    # ---------------------------------------------------------
    # LINE CHART 2: MONTHLY PURCHASE ORDER VOLUME / COUNT
    # ---------------------------------------------------------
    monthly_volume = (
        confirmed_purchase_orders
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
    # TOP 5 PURCHASED PRODUCTS PER MONTH (Incoming StockMoveLines)
    # ---------------------------------------------------------
    movement_lines = StockMoveLine.objects.filter(
        move__product__company=company,
        move__status=StockMove.Status.COMPLETED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )

    incoming_lines = movement_lines.filter(
        source_location__usage=SUPPLIER,
        dest_location__usage=INTERNAL,
    )

    top_products = (
        incoming_lines
        .values("move__product__name")
        .annotate(total_quantity=Sum("quantity"))
        .order_by("-total_quantity")[:5]
    )
    top_product_names = [r["move__product__name"] for r in top_products]

    product_monthly_data = (
        incoming_lines
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
    # BEST / LEAST PURCHASED — CURRENT MONTH
    # ---------------------------------------------------------
    this_month_incoming = incoming_lines.filter(
        created_at__gte=_aware(current_month),
        created_at__lt=end_dt
    )

    this_month_purchases = list(
        this_month_incoming
        .values("move__product__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")
    )

    def _ranking(rows):
        return {
            "labels": [r["move__product__name"] for r in rows],
            "data": [float(r["total"] or 0) for r in rows],
        }

    best_selling = _ranking(this_month_purchases[:5])
    least_selling = _ranking(sorted(this_month_purchases, key=lambda r: r["total"])[:5])

    # ---------------------------------------------------------
    # TOP VENDORS BY SPEND
    # ---------------------------------------------------------
    top_vendors_query = list(
        confirmed_purchase_orders
        .values("partner__name")
        .annotate(total=Sum("amount_total"))
        .order_by("-total")[:5]
    )

    top_vendors = {
        "labels": [r["partner__name"] or "Unknown Vendor" for r in top_vendors_query],
        "data": [float(r["total"] or 0) for r in top_vendors_query],
    }

    # ---------------------------------------------------------
    # DONUT CHART PIPELINES (Matching PurchaseOrder Status Choices)
    # ---------------------------------------------------------
    def get_rfq_status():
        counts = purchase_orders.aggregate(
            draft=Count("id", filter=Q(status='DRAFT')),
            sent=Count("id", filter=Q(status='SENT')),
            to_approve=Count("id", filter=Q(status='TO_APPROVE')),
            purchase=Count("id", filter=Q(status='PURCHASE')),
            cancelled=Count("id", filter=Q(status='CANCELLED')),
        )
        return {
            "labels": ["RFQ", "RFQ Sent", "To Approve", "Purchase Order", "Cancelled"],
            "series": [
                counts["draft"],
                counts["sent"],
                counts["to_approve"],
                counts["purchase"],
                counts["cancelled"],
            ],
        }

    def get_purchase_order_status():
        counts = purchase_orders.aggregate(
            purchase=Count("id", filter=Q(status='PURCHASE')),
            done=Count("id", filter=Q(status='DONE')),
            cancelled=Count("id", filter=Q(status='CANCELLED')),
        )
        return {
            "labels": ["Purchase Order", "Locked / Done", "Cancelled"],
            "series": [
                counts["purchase"],
                counts["done"],
                counts["cancelled"],
            ],
        }

    def get_receipt_status_donut():
        counts = purchase_orders.aggregate(
            not_received=Count("id", filter=Q(shipment_status='NOT_RECEIVED')),
            partial=Count("id", filter=Q(shipment_status='PARTIALLY_RECEIVED')),
            received=Count("id", filter=Q(shipment_status='RECEIVED')),
            cancelled=Count("id", filter=Q(shipment_status='CANCELLED')),
        )
        return {
            "labels": ["Not Received", "Partially Received", "Received", "Cancelled"],
            "series": [
                counts["not_received"],
                counts["partial"],
                counts["received"],
                counts["cancelled"],
            ],
        }

    def get_purchase_invoice_status_donut():
        counts = purchase_orders.aggregate(
            no=Count("id", filter=Q(invoice_status="no")),
            to_invoice=Count("id", filter=Q(invoice_status="to_invoice")),
            invoiced=Count("id", filter=Q(invoice_status="invoiced")),
        )
        return {
            "labels": ["Nothing to Bill", "To Bill", "Fully Billed"],
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
        "top_vendors": top_vendors,
        "pie_quotations": get_rfq_status(),
        "pie_purchases": get_purchase_order_status(),
        "pie_receipt": get_receipt_status_donut(),
        "pie_invoices": get_purchase_invoice_status_donut(),
    })