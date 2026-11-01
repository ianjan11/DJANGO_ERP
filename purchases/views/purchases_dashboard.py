from pygments.lexers import data
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from accounting.models import Payment
from purchases.models import PurchaseOrder


@login_required
def purchases_dashboard(request):

    is_accountant = request.user.groups.filter(name="accountants").exists()

    if is_accountant:
        purchases = PurchaseOrder.objects.all()
        draft_purchases = PurchaseOrder.objects.filter(status="Draft").count()
    else:
        purchases = PurchaseOrder.objects.filter(created_by=request.user)
        draft_purchases = PurchaseOrder.objects.filter(
            status="Draft",
            created_by=request.user
        ).count()


    context = {
        "purchases": purchases,
    }

    if request.headers.get("HX-Request"):
        return render(request, "purchases/partials/dashboard_content.html", context)

    # normal page
    return render(request, 'purchases/purchases_dashboard.html', {
        **context,
    })

