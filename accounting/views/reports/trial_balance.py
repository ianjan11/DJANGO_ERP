from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import date

from accounting.services.balance_data import get_data
from accounting.utils import _parse_date


@login_required
def trial_balance(request):
    target_date = _parse_date(request.GET.get('target_date')) or date.today()
    data = get_data(request.company, target_date)

    # Split into sections by account type for display
    rows = list(data.values())

    total_debit = sum(r['total_debit'] for r in rows)
    total_credit = sum(r['total_credit'] for r in rows)
    difference = total_debit - total_credit

    context = {
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'target_date': target_date,
        'balanced': total_debit == total_credit,
        'difference': difference,
    }

    if request.headers.get("HX-Request"):
        return render(request, 'accounting/reports/partials/trial_balance_partial.html', context)

    return render(request, 'accounting/reports/trial_balance.html', context)
