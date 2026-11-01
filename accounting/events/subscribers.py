from accounting.events.types import AccountingEventType
from core.events.dispatcher import register

from accounting.events.handlers.invoice import (handle_invoice_created, handle_invoice_deleted,
                                           handle_reset_to_draft, handle_invoice_cancelled, handle_invoice_confirmed,
                                           handle_invoice_posted)



def register_handlers():

    # ─── Invoice Events ───

    register(
        AccountingEventType.INVOICE_CREATED,
        handle_invoice_created
    )

    register(
        AccountingEventType.INVOICE_DELETED,
        handle_invoice_deleted
    )

    register(
        AccountingEventType.INVOICE_RESET_TO_DRAFT,
        handle_reset_to_draft
    )


    register(
        AccountingEventType.INVOICE_CANCELLED,
        handle_invoice_cancelled
    )

    register(
        AccountingEventType.INVOICE_CONFIRMED,
    handle_invoice_confirmed
    )

    register(
        AccountingEventType.INVOICE_POSTED,
        handle_invoice_posted
    )

