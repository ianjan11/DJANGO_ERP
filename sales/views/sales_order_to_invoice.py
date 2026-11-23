import logging
from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse

from accounting.services.invoice.order_to_invoice import order_to_invoice
from sales.services import load_sales_order

logger = logging.getLogger('sales.invoice')


@login_required
def sales_to_invoice_view(request, order_id, transaction=None):

    detail_url = reverse("sales:sales_order_create_or_detail", kwargs={"order_id": order_id})

    return order_to_invoice(
        request,
        order_id=order_id,
        origin_type="sales_order",
        detail_url=detail_url,
        target="#sales-display",
    )