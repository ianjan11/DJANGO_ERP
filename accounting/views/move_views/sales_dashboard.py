from pygments.lexers import data
from django.shortcuts import render
from django.contrib.auth.decorators import login_required



@login_required
def sales_dashboard(request):

    is_accountant = request.user.groups.filter(name="accountants").exists()


    if request.headers.get("HX-Request"):
        return render(request, "sales/partials/dashboard_content.html")

    # normal page
    return render(request, 'sales/sales_dashboard.html')

