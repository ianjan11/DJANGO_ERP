from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from inventory.models import StockPicking


@login_required
def inventory_dashboard(request):


    deliveries = StockPicking.objects.filter(company=request.company)



    context = {
        "deliveries": deliveries,
    }

    if request.headers.get("HX-Request"):
        return render(request, "inventory/partials/dashboard_contents.html", {**context})

    # normal page
    return render(request, 'inventory/inventory_dashboard.html', {
        **context,
    })