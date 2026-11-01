import logging

logger = logging.getLogger("sales.invoice")


def log_event(event):
    logger.debug(
        f"[EVENT] {event.type} | "
        f"invoice={event.invoice_id} | "
        f"user={event.user_id} | "
        f"payload={event.payload}"
    )