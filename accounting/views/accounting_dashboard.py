from pygments.lexers import data
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from accounting.models import Payment


@login_required
def accounting_dashboard(request):



    if request.headers.get("HX-Request"):
        return render(request, "accounting/partials/dashboard_content.html")


    return render(request, 'accounting/accounting_dashboard.html')

