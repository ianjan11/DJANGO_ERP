import logging

from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse
from accounting.services.invoice.order_to_invoice import order_to_invoice
from purchases.services.purchase_order_loader import load_purchase_order

logger = logging.getLogger('sales.invoice')




@login_required
def purchase_to_invoice_view(request, purchase_id):
    detail_url = reverse("purchases:purchase_create_or_detail", kwargs={"purchase_id": purchase_id})

    purchase_order = load_purchase_order(purchase_id, request, for_update=True)

    return order_to_invoice(
        request,
        order=purchase_order,
        origin_type="purchase_order",
        detail_url=detail_url,
        target="#purchases-display",
    )

