from datetime import datetime, date
from itertools import groupby
from django.shortcuts import render
from django.urls import reverse
from django.db.models import Sum, Q

from accounting.models import AccountMoveLine, Account
from accounting.utils.get_fiscal_year import get_fiscal_year_start
from core.utils import htmx_error


def get_general_ledger(request):
    company = request.company

    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    try:
        end_date = (
            datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if end_date_str else date.today()
        )
        start_date = (
            datetime.strptime(start_date_str, '%Y-%m-%d').date()
            if start_date_str else get_fiscal_year_start(company, as_of=end_date)
        )
    except ValueError:
        return htmx_error(request, "Invalid date format, expected YYYY-MM-DD.")

    if start_date > end_date:
        return htmx_error(request, "start_date must be on or before end_date.")

    search_account = request.GET.get('search_account')
    reconciled_status = request.GET.get('reconciled_status')

    base_qs = AccountMoveLine.objects.filter(
        move__company=company,
        move__state='posted',
    )

    if reconciled_status:
        if reconciled_status == "reconciled":
            base_qs = base_qs.filter(reconciled=True)
        else:
            base_qs = base_qs.filter(reconciled=False)

    if search_account:
        base_qs = base_qs.filter(
            Q(account__code__icontains=search_account) |
            Q(account__name__icontains=search_account)
        )

    lines = base_qs.filter(
        date__gte=start_date, date__lte=end_date
    ).select_related('move', 'account').order_by('account__code', 'date', 'move_id')

    # Opening balances per account present in this range
    account_ids = lines.values_list('account_id', flat=True).distinct()
    opening_balances = {
        row['account']: (row['debit'] or 0) - (row['credit'] or 0)
        for row in AccountMoveLine.objects.filter(
            move__company=company, move__state='posted',
            account_id__in=account_ids, date__lt=start_date,
        ).values('account').annotate(debit=Sum('debit'), credit=Sum('credit'))
    }

    grouped = []
    grand_total_debit = 0
    grand_total_credit = 0

    # Group lines by account, computing running balance and totals
    for account, account_lines in groupby(lines, key=lambda l: l.account):
        account_lines = list(account_lines)
        balance = opening_balances.get(account.id, 0)

        acc_total_debit = 0
        acc_total_credit = 0
        rows = []

        for line in account_lines:
            debit = line.debit or 0
            credit = line.credit or 0

            acc_total_debit += debit
            acc_total_credit += credit
            balance += debit - credit

            rows.append({'line': line, 'running_balance': balance})

        grand_total_debit += acc_total_debit
        grand_total_credit += acc_total_credit

        grouped.append({
            'account': account,
            'opening_balance': opening_balances.get(account.id, 0),
            'total_debit': acc_total_debit,
            'total_credit': acc_total_credit,
            'closing_balance': balance,
            'rows': rows,
        })

    context = {
        'grouped_accounts': grouped,
        'grand_total_debit': grand_total_debit,
        'grand_total_credit': grand_total_credit,
        'start_date': start_date,
        'end_date': end_date,
        'company': company,
        'report_url': reverse('accounting:general_ledger'),
        'selected_reconciled_status': reconciled_status,
        'all_accounts': Account.objects.filter(company=company).order_by('code'),
    }

    template = (
        'accounting/reports/partials/general_ledger_partial.html'
        if request.headers.get("HX-Request")
        else 'accounting/reports/general_ledger.html'
    )
    return render(request, template, context)