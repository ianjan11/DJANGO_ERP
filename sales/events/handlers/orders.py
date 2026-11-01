from sales.events.loggs.invoice_logger import logger
from sales.models import  SalesOrder


def _extract_event_data(event):
    """Helper to cleanly extract payload and user_id regardless of event structure."""
    if isinstance(event, dict):
        payload = event.get("payload", event)
        user_id = event.get("user_id") or event.get("context", {}).get("user_id")
    else:
        payload = getattr(event, "payload", {})
        context = getattr(event, "context", None)
        user_id = getattr(context, "user_id", None) if context else getattr(event, "user_id", None)

    return payload, user_id


def handle_order_created(event):
    payload, _ = _extract_event_data(event)
    invoice_id = payload.get("order_id") or payload.get("invoice_id")

    if not invoice_id:
        logger.error("Invoice or Order ID missing from event payload")
        return {"status": "error", "reason": "missing_invoice_id"}

    try:
        invoice = SalesOrder.objects.get(id=invoice_id)
        logger.info("Invoice created handled: %s", invoice.id)
        return {"status": "success", "invoice_id": invoice.id}

    except SalesOrder.DoesNotExist:
        logger.error("SalesOrder %s not found during event handling", invoice_id)
        return {"status": "error", "reason": "invoice_not_found"}

    except Exception:
        logger.exception("Error processing INVOICE_CREATED event for %s", invoice_id)
        return {"status": "error", "reason": "processing_failed"}


def handle_order_deleted(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info("Sales Order %s deleted by user %s", order_id, user_id)
        return {"status": "ok", "order_id": order_id}

    except Exception:
        logger.exception("Failed to handle order.deleted event for %s", order_id)
        return {"status": "error", "reason": "processing_failed"}


def handle_reset_to_quotation(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info("Sales Order %s reset to quotation/draft by user %s", order_id, user_id)
        return {"status": "ok", "order_id": order_id}

    except Exception:
        logger.exception("Failed to handle order.resetToQuotation event for %s", order_id)
        return {"status": "error", "reason": "processing_failed"}


def handle_order_cancelled(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info("Sales Order %s cancelled by user %s", order_id, user_id)
        return {"status": "ok", "order_id": order_id}

    except Exception:
        logger.exception("Failed to handle sales order cancellation for %s", order_id)
        return {"status": "error", "reason": "processing_failed"}


def handle_delivery_recreated(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")
    delivery_id = payload.get("delivery_id")

    try:
        logger.info(
            "Delivery %s recreated for Sales Order %s by user %s",
            delivery_id, order_id, user_id
        )
        return {
            "status": "ok",
            "order_id": order_id,
            "delivery_id": delivery_id
        }

    except Exception:
        logger.exception(
            "Failed to handle delivery recreated event for order %s, delivery %s",
            order_id, delivery_id
        )
        return {"status": "error", "reason": "processing_failed"}

def handle_order_confirmed(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info(
            "Sales Order %s confirmed by user %s",
            order_id, user_id
        )
        return {
            "status": "ok",
            "order_id": order_id,
        }

    except Exception:
        logger.exception(
            "Failed to handle order.confirmed event for order %s",
            order_id
        )
        return {"status": "error", "reason": "processing_failed"}


def handle_reset_to_draft(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info(
            "Sales Order %s reset to draft by user %s",
            order_id, user_id
        )
        return {
            "status": "ok",
            "order_id": order_id,
        }

    except Exception:
        logger.exception(
            "Failed to handle order.resetToDraft event for order %s",
            order_id
        )
        return {"status": "error", "reason": "processing_failed"}


def handle_order_sent(event):
    payload, user_id = _extract_event_data(event)
    order_id = payload.get("order_id")

    try:
        logger.info(
            "Sales Order %s marked as sent by user %s",
            order_id, user_id
        )
        return {
            "status": "ok",
            "order_id": order_id,
        }

    except Exception:
        logger.exception(
            "Failed to handle order.sent event for order %s",
            order_id
        )
        return {"status": "error", "reason": "processing_failed"}