from pygments.lexers import data
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from accounting.models import Payment


@login_required
def accounting_dashboard(request):

    is_accountant = request.user.groups.filter(name="accountants").exists()

    if is_accountant:
        payments = Payment.objects.all()
        draft_payments = Payment.objects.filter(state="Draft").count()
    else:
        payments = Payment.objects.filter(created_by=request.user)
        draft_payments = Payment.objects.filter(
            state="Draft",
            created_by=request.user
        ).count()


    context = {
        "payments": payments,
    }

    if request.headers.get("HX-Request"):
        return render(request, "accounting/partials/dashboard_content.html", context)

    # normal page
    return render(request, 'accounting/accounting_dashboard.html', {
        **context,
    })

