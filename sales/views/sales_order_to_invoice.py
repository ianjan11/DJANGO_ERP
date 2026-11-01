import logging
from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse

from accounting.services.invoice.order_to_invoice import order_to_invoice
from sales.services import load_sales_order

logger = logging.getLogger('sales.invoice')





@login_required
def sales_to_invoice_view(request, order_id):
    detail_url = reverse("sales:sales_order_create_or_detail", kwargs={"order_id": order_id})

    order = load_sales_order(order_id, request=request, for_update=True)

    return order_to_invoice(
        request,
        order=order,
        origin_type="sales_order",
        detail_url=detail_url,
        target="#sales-display",
    )