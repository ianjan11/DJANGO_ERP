from returns.models import Return
from accounting.models import Invoice
from sales.events.loggs.invoice_logger import logger


def handle_invoice_created(event):

    try:
        invoice_id = event.get("invoice_id")

        if not invoice_id:
            logger.error("invoice_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_invoice_id"
            }

        invoice = Invoice.objects.get(id=invoice_id)

        logger.info(f"Invoice created handled: {invoice.id}")

        return {
            "status": "success",
            "invoice_id": invoice.id
        }

    except Invoice.DoesNotExist:
        logger.error(f"Invoice {invoice_id} not found during event handling")

        return {
            "status": "error",
            "reason": "invoice_not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing INVOICE_CREATED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }



def handle_invoice_deleted(event):
    try:
        payload = event.payload
        invoice_id = payload.get("invoice_id")

        logger.info("Invoice %s deleted by user %s", invoice_id, event.context.user_id)

        return {"status": "ok", "invoice_id": invoice_id}

    except Exception as e:
        logger.exception("Failed to handle invoice.delete event: %s", e)
        return {"status": "error", "reason": str(e)}



def handle_reset_to_draft(event):
    payload = event.payload
    try:

        logger.info(
            "Invoice %s reset to draft by user %s",
            payload["invoice_id"], event.context.user_id
        )
        return {"status": "ok", "invoice_id": payload["invoice_id"]}

    except Exception as e:
        logger.exception("Failed to handle invoice.reset_to_draft event: %s", e)
        return {"status": "error", "reason": str(e)}



def handle_invoice_cancelled(event):
    try:
        payload = event.payload
        invoice_id = payload.get("invoice_id")
        amount = payload.get("amount")


        logger.info("Reversal move created for invoice %s", invoice_id)

    except Exception as e:
        logger.exception("Failed to create reversal move for invoice %s: %s", invoice_id, e)



# accounting/handlers.py
def handle_invoice_confirmed(event):
    try:
        payload = event.payload
        logger.info(
            "Invoice %s confirmed by user %s, amount: %s",
            payload.get("invoice_id"),
            event.context.user_id,
            payload.get("amount"),
        )
    except Exception as e:
        logger.exception("Failed to handle invoice confirmed event: %s", e)


def handle_invoice_posted(event):
    try:
        payload = event.payload
        logger.info(
            "Invoice %s posted by user %s, amount: %s",
            payload.get("invoice_id"),
            event.context.user_id,
            payload.get("amount"),
        )
    except Exception as e:
        logger.exception("Failed to handle invoice confirmed event: %s", e)