from datetime import timedelta
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from pygments.lexers import data
from django.db.models import Sum, Count, Q
from decimal import Decimal
from sales.models import SalesOrder
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
import logging
from django.utils import timezone

logger = logging.getLogger('sales.invoice')


def _build_context(request, orders):

    summary = orders.aggregate(
        total_amount=Sum('amount_total'),
        paid_amount=Sum('amount_total', filter=Q(payment_state='paid')),
        unpaid_amount=Sum('amount_total', filter=Q(payment_state='not_paid')),
        total_count=Count('id'),
        paid_count=Count('id', filter=Q(payment_state='paid')),
        unpaid_count=Count('id', filter=Q(payment_state='not_paid')),
        draft_count=Count('id', filter=Q(status='DRAFT')),
        posted_count=Count('id', filter=Q(status='CONFIRMED')),
        completed_count=Count('id', filter=Q(status='SENT')),
        cancelled_count=Count('id', filter=Q(status='DONE')),
    )

    # guard against None when queryset is empty
    summary = {k: v or Decimal('0') if 'amount' in k else v or 0
               for k, v in summary.items()}

    # — order + paginate
    orders = orders.order_by('-created_at')
    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'orders': page_obj,
        'summary': summary,
    }
    return context

@login_required
def sales_orders_list(request):

    if request.user.is_staff:
       orders = SalesOrder.objects.filter(company=request.company).order_by('-created_at').select_related('partner','created_by')
    else:
        orders = (SalesOrder.objects
                    .filter(created_by=request.user, company=request.company)
                    .select_related('partner', 'created_by')
                    .prefetch_related('pickings').order_by('-created_at'))


    today = timezone.now().date()

    # — search
    search_order = request.GET.get('search_order')
    if search_order:
        orders = orders.filter(
            Q(order_number__icontains=search_order) |
            Q(customer__name__icontains=search_order)
        )

    # — status
    order_status = request.GET.get('order_status')
    if order_status:
        orders = orders.filter(status=order_status)

    preset = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        orders = orders.filter(issue_date=target_date)
    elif preset == 'Today':
        orders = orders.filter(issue_date=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(issue_date__gte=week_start)
    elif preset == 'ThisMonth':
        orders = orders.filter(issue_date__year=today.year, issue_date__month=today.month)
    elif preset == 'ThisYear':
        orders = orders.filter(issue_date__year=today.year)

    context = _build_context(request, orders)


    if request.headers.get('HX-Request'):
        return render(request, 'sales/partials/orders_table.html',context)

    return render(request, 'sales/orders_list.html',
                  context)












