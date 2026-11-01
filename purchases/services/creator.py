from django.utils import timezone
from core.models import SequenceRegistry
from core.services.partner_defaults import resolve_document_defaults, DocumentType
from purchases.models import PurchaseOrder


def create_purchase(request, company_id, partner=None):
    """
    Creates a draft purchase order. If partner is None, defaults are pulled
    from user profile / company fallbacks.
    """
    user = request.user
    defaults = resolve_document_defaults(
        user, DocumentType.PURCHASE_ORDER, partner=partner
    )


    order = PurchaseOrder.objects.create(
        status="DRAFT",
        created_by=user,
        partner=partner,
        currency=defaults["currency"].value or request.company.currency,
        payment_term=defaults["payment_term"].value,
        fulfillment_location=defaults["location"].value,
        company_id=company_id,
    )

    return order


def refresh_purchase_order_defaults(order, user, partner):
    """
    Refreshes defaults on a draft Purchase Order when a vendor is (re)selected.
    """
    defaults = resolve_document_defaults(
        user, DocumentType.PURCHASE_ORDER, partner=partner, source_document=order
    )

    order.partner = partner
    order.currency = defaults["currency"].value
    order.payment_term = defaults["payment_term"].value
    order.fulfillment_location = defaults["location"].value

    order.save(
        update_fields=[
            "partner",
            "currency",
            "payment_term",
            "fulfillment_location",
        ]
    )

    return order, defaults


def create_reference(company_id):
    seq = SequenceRegistry.get_next_sequence("PURCHASE", company_id)
    date_str = timezone.now().date().strftime("%Y%m%d")
    return f"PUR-{date_str}-{seq:05d}"