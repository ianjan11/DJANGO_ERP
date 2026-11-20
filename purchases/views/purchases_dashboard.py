from pygments.lexers import data
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from accounting.models import Payment
from purchases.models import PurchaseOrder


@login_required
def purchases_dashboard(request):

    if request.headers.get("HX-Request"):
        return render(request, "purchases/partials/dashboard_content.html")

    # normal page
    return render(request, 'purchases/purchases_dashboard.html', )

