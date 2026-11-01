from django.utils import timezone

from django.db import transaction

from core.models import SequenceRegistry
from core.models.currency import CompanyCurrency
from core.services.partner_defaults import resolve_document_defaults, DocumentType
from sales.models import SalesOrder


def create_sales_order(request,):
    """
    customer is optional: a blank draft can be started before a customer is
    picked (defaults then come only from the salesperson's profile), and the
    order can be updated with real customer-driven defaults once one is set —
    see refresh_sales_order_defaults() below for that second step.
    """
    defaults = resolve_document_defaults(
         request.user, DocumentType.SALE_ORDER
    )
    company = request.company


    order = SalesOrder.objects.create(
        status="DRAFT",
        created_by=request.user,
        fulfillment_location=defaults["location"].value,
        currency=defaults["currency"].value or company.currency,
        payment_term=defaults["payment_term"].value,
        company=request.company,
    )

    return order


def refresh_sales_order_defaults(order, user, customer):
    """
    Call this when a customer is (re)selected on an existing draft order —
    e.g. an onChange handler on the customer field in the UI. Only touches
    fields the user hasn't already overridden isn't handled here; if you
    need that, track a per-field "user_edited" flag and skip resolved
    fields that are already dirty.
    """
    defaults = resolve_document_defaults(
        user, DocumentType.SALE_ORDER, partner=customer, source_document=order
    )

    order.partner = customer
    order.destination_location = defaults["location"].value
    order.currency = defaults["currency"].value
    order.payment_term = defaults["payment_term"].value
    order.save(update_fields=["partner", "destination_location", "currency", "payment_term"])

    return order, defaults



def generate_order_number(company):
    seq = SequenceRegistry.get_next_sequence('SALES_ORDER', company)
    date_str = timezone.now().date().strftime("%Y%m%d")
    reference = f"SO-{date_str}-{seq:05d}"
    return reference

