from datetime import date, timedelta
import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render, get_object_or_404
from django.urls import reverse, NoReverseMatch
from django.utils import timezone

from inventory.forms.stock_operation_form import StockPickingHeaderForm, StockMoveFormSet
from inventory.models import StockPicking, StockPickingType

logger = logging.getLogger(__name__)

PICKING_TYPE_MAPPING = {
    "incoming": StockPickingType.Code.INCOMING,
    "outgoing": StockPickingType.Code.OUTGOING,
    "return": StockPickingType.Code.RETURN,
    "internal": StockPickingType.Code.INTERNAL,
}

PICKING_LIST_URLS = {
    "incoming": "inventory:receipt_list",
    "outgoing": "inventory:delivery_list",
    "return": "inventory:return_list",
    "internal": "inventory:internal_transfer_list",
}


@login_required
def receipts_view(request):
    return get_pickings(request, "incoming")

@login_required
def deliveries_view(request):
    return get_pickings(request, "outgoing")

@login_required
def returns_view(request):
    return get_pickings(request, "return")

@login_required
def internal_transfers_view(request):
    return get_pickings(request, "internal")

@login_required
def get_pickings(request, picking_type=None):

    code = PICKING_TYPE_MAPPING.get(picking_type)

    pickings = (
        StockPicking.objects.filter(company=request.company)
        .select_related(
            "picking_type",
            "partner",
            "sales_order",
            "purchase_order",
        )
        .prefetch_related("backorders")
        .order_by("-created_at", "-id")
    )

    if code:
        pickings = pickings.filter(picking_type__code=code)

    today = timezone.localdate()

    # — Search Filter
    search_pickings = request.GET.get("search_pickings")
    if search_pickings:
        pickings = pickings.filter(
            Q(name__icontains=search_pickings)
            | Q(partner__name__icontains=search_pickings)
            | Q(sales_order__order_number__icontains=search_pickings)
            | Q(purchase_order__reference__icontains=search_pickings)
        )

    # — Status Filter
    picking_status = request.GET.get("picking_status")
    if picking_status:
        pickings = pickings.filter(status=picking_status)

    picking_origin = request.GET.get("picking_origin")
    if picking_origin:
        pickings = pickings.filter(
            Q(purchase_order__reference__icontains=picking_origin)
            | Q(sales_order__order_number__icontains=picking_origin)
        )

    # — Date Filters
    preset = request.GET.get("preset")
    target_date = request.GET.get("target_date")

    parsed_target = None
    if target_date:
        try:
            parsed_target = date.fromisoformat(target_date)
        except ValueError:
            parsed_target = None

    if parsed_target:
        pickings = pickings.filter(created_at__date=parsed_target)
    elif preset == "Today":
        pickings = pickings.filter(created_at__date=today)
    elif preset == "ThisWeek":
        week_start = today - timedelta(days=today.weekday())
        pickings = pickings.filter(created_at__date__gte=week_start)
    elif preset == "ThisMonth":
        pickings = pickings.filter(
            created_at__year=today.year, created_at__month=today.month
        )
    elif preset == "ThisYear":
        pickings = pickings.filter(created_at__year=today.year)

    context = _build_context(request, pickings, picking_type)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "inventory/pickings/partials/pickings_table.html",
            context,
        )

    return render(
        request,
        "inventory/pickings/pickings.html",
        context,
    )

def _build_context(request, pickings, picking_type):
    url_name = PICKING_LIST_URLS.get(picking_type)
    filter_url = ""
    if url_name:
        try:
            filter_url = reverse(url_name)
        except NoReverseMatch:
            filter_url = ""

    paginator = Paginator(pickings, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Map open states to pending metrics to match StockPicking.Status choices
    S = StockPicking.Status
    open_states = [S.DRAFT, S.WAITING, S.CONFIRMED, S.ASSIGNED]

    summary = pickings.aggregate(
        total_count=Count("id"),
        pending_count=Count("id", filter=Q(status__in=open_states)),
        completed_count=Count("id", filter=Q(status=S.COMPLETED)),
        cancelled_count=Count("id", filter=Q(status=S.CANCELLED)),
    )

    return {
        "pickings": page_obj,
        "summary": summary,
        "picking_type": picking_type,
        "filter_url": filter_url,
    }