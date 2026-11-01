from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import date
from accounting.services.balance_data import get_balance_sheet_data
from accounting.utils import _parse_date


@login_required
def balance_sheet(request):
    target_date = _parse_date(request.GET.get('target_date')) or date.today()
    data = get_balance_sheet_data(request.company, target_date)
    context = {
        **data,
        'title': 'Balance Sheet',

    }

    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/reports/partials/balance_sheet_partial.html",
            context,
        )


    return render(
        request,
        "accounting/reports/balance_sheet.html",
        context,
    )

