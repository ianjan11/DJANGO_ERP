import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.urls import reverse

from accounting.events.accounting_events import create_event
from accounting.events.types import AccountingEventType
from accounting.services.invoice.to_invoice_service import to_invoice
from core.events import dispatch
from core.utils import htmx_success, htmx_error
from purchases.services.purchase_order_loader import load_purchase_order
from sales.services import load_sales_order
logger = logging.getLogger('sales.invoice')

def order_to_invoice(request, *, order, origin_type, detail_url, target):
    """
    Shared create-invoice flow for both purchase orders and sales orders.
    """
    invoice_id = None

    try:
        with transaction.atomic():
            invoice = to_invoice(origin_type=origin_type, source=order, user=request.user)
            invoice_id = invoice.id

            logger.debug("Created invoice %s from %s", invoice_id, origin_type)

            event = create_event(
                event_type=AccountingEventType.INVOICE_CREATED,
                user_id=request.user.id,
                source="htmx" if request.headers.get('HX-Request') else "web",
                payload={
                    "invoice_id": invoice_id
                },
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        message = " ".join(e.messages) if hasattr(e, "messages") else str(e)
        return htmx_error(request, message, detail_url)

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to create this invoice.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception("Failed to create invoice from %s (invoice_id=%s)", origin_type, invoice_id)
        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    success_url = reverse("accounting:invoice_create_or_detail", kwargs={"invoice_id": invoice_id})

    return htmx_success(
        request,
        message="Invoice created successfully.",
        redirect_url=success_url,
        target=target,
    )

