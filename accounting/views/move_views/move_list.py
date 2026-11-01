from datetime import timedelta
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q
from accounting.models import AccountMove
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import logging
from django.utils import timezone


logger = logging.getLogger('sales.invoice')


def get_invoices(request, move_type):

    if request.user.is_staff:
        invoices = (AccountMove.objects
                    .filter(company=request.company, move_type=move_type)
                    .order_by('-created_at')
                    .select_related('partner', 'created_by'))
    else:
        invoices = (AccountMove.objects
                    .filter(created_by=request.user, company=request.company, move_type=move_type)
                    .select_related('partner', 'created_by')
                    .order_by('-created_at'))
        # .prefetch_related('account_move') is gone: AccountMove *is* the move now,
        # there's no separate related object to prefetch.

    today = timezone.now().date()

    # — search
    search_invoice = request.GET.get('search_invoice')
    if search_invoice:
        invoices = invoices.filter(
            Q(name__icontains=search_invoice) |
            Q(partner__name__icontains=search_invoice)
        )

    # — status
    # AccountMove.State is lowercase ('draft'/'posted'/'cancelled'), unlike the old
    # Invoice.STATUS ('DRAFT'/'POSTED'/'CANCELLED'); normalize whatever the client sends.
    invoice_status = request.GET.get('invoice_status')
    if invoice_status:
        invoices = invoices.filter(state=invoice_status.lower())

    preset = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        invoices = invoices.filter(issue_date=target_date)
    elif preset == 'Today':
        invoices = invoices.filter(issue_date=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        invoices = invoices.filter(issue_date__gte=week_start)
    elif preset == 'ThisMonth':
        invoices = invoices.filter(issue_date__year=today.year, issue_date__month=today.month)
    elif preset == 'ThisYear':
        invoices = invoices.filter(issue_date__year=today.year)

    # — order + paginate
    invoices = invoices.order_by('-created_at')
    paginator = Paginator(invoices, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    summary = invoices.aggregate(
        total_amount=Sum('amount_total'),
        paid_amount=Sum('amount_total', filter=Q(payment_state='paid')),
        unpaid_amount=Sum('amount_total', filter=Q(payment_state='not_paid')),
        total_count=Count('id'),
        paid_count=Count('id', filter=Q(payment_state='paid')),
        unpaid_count=Count('id', filter=Q(payment_state='not_paid')),
        draft_count=Count('id', filter=Q(state='draft')),
        posted_count=Count('id', filter=Q(state='posted')),
        cancelled_count=Count('id', filter=Q(state='cancelled')),
        # 'completed_count'/'COMPLETED' from the old version is dropped: neither the old
        # Invoice.STATUS nor AccountMove.State ever had a COMPLETED value — that filter
        # always matched zero rows.
    )

    context = {
        'invoices': page_obj,
        'summary': summary,
        'invoice_type': move_type,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'accounting/move_templates/partials/move_table.html', context)

    return render(request, 'accounting/move_templates/move_list.html', context)

@login_required
def customer_invoices(request):
    return get_invoices(request, 'out_invoice')

@login_required
def vendor_invoices(request):
    return get_invoices(request, 'in_invoice')

@login_required
def customer_credit_notes_view(request):
    return get_invoices(request, 'out_refund')

@login_required
def vendor_credit_notes_view(request):
    return get_invoices(request, 'in_refund')