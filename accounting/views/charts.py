
from accounting.models import AccountMove
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from datetime import datetime, time, date
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Sum,
    Count,
    Q,
)
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils import timezone




def _aware(d):
    """date -> timezone-aware datetime at 00:00 (avoids naive-datetime warnings)."""
    return timezone.make_aware(datetime.combine(d, time.min))




@login_required
def accounting_view_charts(request):
    company = request.company
    today = timezone.localdate()

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
        """Safely format datetime or date objects as 'YYYY-MM'."""
        if isinstance(dt, datetime):
            return timezone.localtime(dt).strftime("%Y-%m") if timezone.is_aware(dt) else dt.strftime("%Y-%m")
        elif isinstance(dt, date):
            return dt.strftime("%Y-%m")
        return str(dt)

    # Base Account Moves in Date Range (Posted/Active)
    moves = AccountMove.objects.filter(
        company=company,
        issue_date__gte=start_month,
        issue_date__lt=end_month,
    )

    posted_moves = moves.filter(state=AccountMove.State.POSTED)

    # ---------------------------------------------------------
    # LINE CHART: MONTHLY INVOICED REVENUE VS VENDOR BILLS (Last 12 Months)
    # ---------------------------------------------------------
    monthly_invoices = (
        posted_moves
        .filter(move_type=AccountMove.MoveType.OUT_INVOICE)
        .annotate(month=TruncMonth("issue_date"))
        .values("month")
        .annotate(total=Sum("amount_total"))
        .order_by("month")
    )

    monthly_bills = (
        posted_moves
        .filter(move_type=AccountMove.MoveType.IN_INVOICE)
        .annotate(month=TruncMonth("issue_date"))
        .values("month")
        .annotate(total=Sum("amount_total"))
        .order_by("month")
    )

    invoice_map = {_key(r["month"]): r["total"] or Decimal("0") for r in monthly_invoices}
    bill_map = {_key(r["month"]): r["total"] or Decimal("0") for r in monthly_bills}

    line_chart = {
        "labels": month_labels,
        "series": [
            {
                "name": "Customer Invoices",
                "data": [float(invoice_map.get(m.strftime("%Y-%m"), Decimal("0"))) for m in months],
            },
            {
                "name": "Vendor Bills",
                "data": [float(bill_map.get(m.strftime("%Y-%m"), Decimal("0"))) for m in months],
            },
        ],
    }

    # ---------------------------------------------------------
    # TOP 5 CUSTOMERS BY OUTSTANDING / INVOICED REVENUE
    # ---------------------------------------------------------
    top_customers_query = list(
        posted_moves
        .filter(move_type=AccountMove.MoveType.OUT_INVOICE)
        .values("partner__name")
        .annotate(total=Sum("amount_total"))
        .order_by("-total")[:5]
    )

    top_customers = {
        "labels": [r["partner__name"] or "Unknown Customer" for r in top_customers_query],
        "data": [float(r["total"] or 0) for r in top_customers_query],
    }

    # ---------------------------------------------------------
    # TOP 5 VENDORS BY BILLED EXPENSES
    # ---------------------------------------------------------
    top_vendors_query = list(
        posted_moves
        .filter(move_type=AccountMove.MoveType.IN_INVOICE)
        .values("partner__name")
        .annotate(total=Sum("amount_total"))
        .order_by("-total")[:5]
    )

    top_vendors = {
        "labels": [r["partner__name"] or "Unknown Vendor" for r in top_vendors_query],
        "data": [float(r["total"] or 0) for r in top_vendors_query],
    }

    # ---------------------------------------------------------
    # DONUT CHART PIPELINES (Matching AccountMove States & Payment States)
    # ---------------------------------------------------------
    def get_move_state_donut():
        counts = moves.aggregate(
            draft=Count("id", filter=Q(state=AccountMove.State.DRAFT)),
            posted=Count("id", filter=Q(state=AccountMove.State.POSTED)),
            cancelled=Count("id", filter=Q(state=AccountMove.State.CANCELLED)),
        )
        return {
            "labels": ["Draft", "Posted", "Cancelled"],
            "series": [counts["draft"], counts["posted"], counts["cancelled"]],
        }

    def get_invoice_payment_state_donut():
        invoices = posted_moves.filter(move_type__in=AccountMove.INVOICE_TYPES)
        counts = invoices.aggregate(
            not_paid=Count("id", filter=Q(payment_state=AccountMove.PaymentState.NOT_PAID)),
            partial=Count("id", filter=Q(payment_state=AccountMove.PaymentState.PARTIAL)),
            paid=Count("id", filter=Q(payment_state=AccountMove.PaymentState.PAID)),
        )
        return {
            "labels": ["Not Paid", "Partially Paid", "Paid"],
            "series": [counts["not_paid"], counts["partial"], counts["paid"]],
        }

    def get_journal_types_donut():
        counts = posted_moves.values("journal__name").annotate(total=Count("id")).order_by("-total")[:4]
        return {
            "labels": [r["journal__name"] or "General" for r in counts],
            "series": [r["total"] for r in counts],
        }

    return JsonResponse({
        "line_chart": line_chart,
        "top_customers": top_customers,
        "top_vendors": top_vendors,
        "pie_move_states": get_move_state_donut(),
        "pie_payment_states": get_invoice_payment_state_donut(),
        "pie_journals": get_journal_types_donut(),
    })