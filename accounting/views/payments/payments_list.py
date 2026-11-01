from django.db.models import  Count, Q
import logging
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from accounting.forms import PaymentForm
from accounting.models import  Journal,Payment
from core.models import Currency
from django.utils import timezone
from datetime import timedelta
from core.models import Partner


logger=logging.getLogger(__name__)


@login_required
def customer_payments(request):
    return get_payments(request, 'customer')

@login_required
def vendor_payments(request):
   return get_payments(request, 'supplier')

def get_payments(request, partner_type):
    payments = (
        Payment.objects
        .filter(partner_type=partner_type, company=request.company).select_related(
            'partner',      # vendor/supplier name
            'journal',      # bank/cash journal
            'currency',     # payment currency
            'company',      # scoping
        )
        .order_by('-date', '-id')
    )



    today = timezone.now().date()

    # — search
    search_payments = request.GET.get('search_payments')
    if search_payments:
        payments = payments.filter(
            Q(payment_number__icontains=search_payments) |
            Q(partner__name=search_payments)
        )

    # — status
    payment_state = request.GET.get('payment_state')
    if payment_state:
        payments = payments.filter(state= payment_state)

    preset = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        payments = payments.filter(created_at=target_date)
    elif preset == 'Today':
        payments = payments.filter(created_at=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        payments = payments.filter(created_at__gte=week_start)
    elif preset == 'ThisMonth':
        payments = payments.filter(created_at__year=today.year, created_at__month=today.month)
    elif preset == 'ThisYear':
        payments = payments.filter(created_at__year=today.year)


    context = _build_context(request,payments,partner_type)



    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/payments_templates/partials/table.html",
            context,
        )


    return render(
        request,
        "accounting/payments_templates/payments_list.html",
        context,
    )

def _build_context(request,payments, partner_type):
    partners = Partner.objects.filter(is_active=True, company=request.company)
    journals = Journal.objects.filter(
        company=request.company,
        type__in=['CASH', 'BANK']
    )
    currencies = Currency.objects.all()
    payment_form = PaymentForm(user=request.user)

    paginator = Paginator(payments, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    summary = payments.aggregate(
        total_count=Count("id"),
        draft_count=Count("id", filter=Q(state="DRAFT")),
        posted_count=Count("id", filter=Q(state="POSTED")),
        reconciled_count=Count("id", filter=Q(state="RECONCILED")),
        cancelled_count=Count("id", filter=Q(state="CANCELLED")),
    )

    context = {
        "payments": page_obj,
        "summary": summary,
        "partner_type": partner_type,
        'partners': partners,
        'journals': journals,
        'currencies': currencies,
        'payment_form': payment_form,
    }

    return context

@login_required
def refresh_payments(request):
    partner_type = request.GET.get("partner_type")
    return get_payments(request, partner_type)