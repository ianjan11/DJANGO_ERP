from pygments.lexers import data
from django.shortcuts import render, get_object_or_404
from core.models import Partner
from django.contrib.auth.decorators import login_required
from sales.models import  SalesOrder



@login_required
def sales_dashboard(request):

    is_accountant = request.user.groups.filter(name="accountants").exists()

    if is_accountant:
        invoices = SalesOrder.objects.all()
        draft_invoices = SalesOrder.objects.filter(status="DRAFT").count()
    else:
        invoices = SalesOrder.objects.filter(created_by=request.user)
        pending_invoices = SalesOrder.objects.filter(
            status="DRAFT",
            created_by=request.user
        ).count()


    context = {
        "invoices": invoices,
    }

    if request.headers.get("HX-Request"):
        return render(request, "sales/partials/dashboard_content.html", context)

    # normal page
    return render(request, 'sales/sales_dashboard.html', {
        **context,
    })

