from core.events.dispatcher import register
from sales.events.handlers.orders import (
    handle_delivery_recreated,
    handle_order_cancelled,
    handle_order_confirmed,
    handle_order_created,
    handle_order_deleted,
    handle_order_sent,
    handle_reset_to_draft,
    handle_reset_to_quotation,
)
from sales.events.types import SalesEventType


def register_handlers():
    """Register event handlers for all sales and order event types."""

    # ─── Order Lifecycle Events ───

    register(
        SalesEventType.ORDER_CREATED,
        handle_order_created
    )

    register(
        SalesEventType.ORDER_SENT,
        handle_order_sent
    )

    register(
        SalesEventType.ORDER_CONFIRMED,
        handle_order_confirmed
    )

    register(
        SalesEventType.ORDER_CANCELLED,
        handle_order_cancelled
    )

    register(
        SalesEventType.ORDER_DELETED,
        handle_order_deleted
    )

    register(
        SalesEventType.ORDER_RESET_TO_QUOTATION,
        handle_reset_to_quotation
    )

    register(
        SalesEventType.ORDER_RESET_TO_DRAFT,
        handle_reset_to_draft
    )

    register(
        SalesEventType.ORDER_DELIVERY_RECREATED,
        handle_delivery_recreated
    )