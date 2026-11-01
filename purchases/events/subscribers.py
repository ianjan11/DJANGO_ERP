from core.events.dispatcher import register
from purchases.events.handlers.purchase import handle_purchase_created, handle_purchase_confirmed, \
    handle_purchase_deleted, handle_purchase_cancelled, handle_purchase_reset_to_draft, handle_purchase_approved, \
    handle_purchase_sent

from purchases.events.types import PurchaseEventType


def register_handlers():

    # ─── Invoice Events ───

    register(
        PurchaseEventType.PURCHASE_CREATED,
        handle_purchase_created
    )
    register(
        PurchaseEventType.PURCHASE_CONFIRMED,
        handle_purchase_confirmed
    )
    register(
        PurchaseEventType.PURCHASE_DELETED,
        handle_purchase_deleted
    )

    register(
        PurchaseEventType.PURCHASE_CANCELLED,
        handle_purchase_cancelled
    )
    register(
        PurchaseEventType.PURCHASE_RESET_TO_DRAFT,
        handle_purchase_reset_to_draft
    )
    register(
        PurchaseEventType.PURCHASE_APPROVED,
        handle_purchase_approved
    )
    register(
        PurchaseEventType.PURCHASE_SENT,
        handle_purchase_sent
    )
