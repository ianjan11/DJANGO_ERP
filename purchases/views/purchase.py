
import logging

from pygments.lexers import data

from django.contrib.auth.decorators import login_required
from purchases.models import PurchaseOrder, PurchaseOrderLine
from datetime import timedelta
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache


logger = logging.getLogger('purchases.invoice')


@login_required
def purchases_list(request):

    if request.user.is_staff:
       purchases = PurchaseOrder.objects.filter(company=request.company).order_by('-created_at').select_related('partner','created_by')
    else:
        purchases = (PurchaseOrder.objects
                    .filter(created_by=request.user, company=request.company)
                    .select_related('partner', 'created_by')
                    .prefetch_related('lines').order_by('-created_at'))



    today = timezone.now().date()

    # ── Search ────────────────────────────────────────────────
    # fixed: was 'search_purchases' — template sends 'search_purchase'
    search_purchase = request.GET.get('search_purchase')
    if search_purchase:
        # fixed: was filtering on undefined `invoices` with invoice fields
        purchases = purchases.filter(
            Q(reference__icontains=search_purchase) |
            Q(supplier__name__icontains=search_purchase)
        )

    # ── Status ────────────────────────────────────────────────
    # fixed: was 'invoice_status' — template sends 'purchase_status'
    purchase_status = request.GET.get('purchase_status')
    if purchase_status:
        # fixed: was filtering undefined `invoices`
        purchases = purchases.filter(status=purchase_status)

    # ── Date presets ─────────────────────────────────────────
    preset      = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        # fixed: was `date=target_date` — PurchaseOrder uses `order_date`
        # fixed: use __date= for DateTimeField or direct for DateField
        purchases = purchases.filter(issue_date=target_date)
    elif preset == 'Today':
        purchases = purchases.filter(issue_date=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        purchases = purchases.filter(issue_date__gte=week_start)
    elif preset == 'ThisMonth':
        purchases = purchases.filter(
            issue_date__year=today.year,
            issue_date__month=today.month
        )
    elif preset == 'ThisYear':
        purchases = purchases.filter(issue_date__year=today.year)

    summary = purchases.aggregate(
        total_count          = Count('id'),
        pending_count        = Count('id', filter=Q(status='PENDING')),
        confirmed_count      = Count('id', filter=Q(status='CONFIRMED')),
        partially_received_count = Count('id', filter=Q(status='PARTIALLY_RECEIVED')),
        received_count       = Count('id', filter=Q(status='RECEIVED')),
        cancelled_count      = Count('id', filter=Q(status='CANCELLED')),
        returned_count       = Count('id', filter=Q(status='RETURNED')),
    )

    # guard against None
    summary = {k: v or 0 for k, v in summary.items()}


    paginator = Paginator(purchases, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)


    context = {
       'purchases': page_obj,
        'summary': summary,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'purchases/partials/purchases_table.html',context)

    return render(request, 'purchases/purchases_list.html',
                  context)




