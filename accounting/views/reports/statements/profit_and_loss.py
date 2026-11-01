from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from datetime import date
from accounting.services.balance_data import get_balance_sheet_data
from accounting.utils import _parse_date


@login_required
def profit_and_loss(request):

    target_date = _parse_date(request.GET.get('target_date')) or date.today()

    data = get_balance_sheet_data(request.company, target_date)

    context = {
        **data,
        'title': 'Profit and Loss',

    }

    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/reports/partials/profit_and_loss_partial.html",
            context,
        )

    return render(
        request,
        "accounting/reports/profit_and_loss.html",
        context,
    )

