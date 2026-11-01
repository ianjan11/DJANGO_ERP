from django.db import transaction
from sales.events.loggs.invoice_logger import logger


def handle_picking_cancelled(event):
    try:
     with transaction.atomic():
        payload = event.payload
        picking_id = payload.get("picking_id")


        logger.info(
            "Picking %s was cancelled",
            picking_id
        )

    except Exception as e:
        logger.exception(
            "Failed to cancel delivery %s",
            picking_id
        )


def handle_picking_confirmed(event):
    try:
      with transaction.atomic():
        payload = event.payload

        logger.info(
            "Picking %s confirmed by user %s,",
            payload.get("picking_id"),
            event.context.user_id,
        )
    except Exception as e:
        logger.exception("Failed to confirm picking: %s", e)