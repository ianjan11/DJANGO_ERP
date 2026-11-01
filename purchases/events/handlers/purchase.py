from purchases.models import PurchaseOrder, IncomingShipment
from returns.models import Return
from sales.events.loggs.invoice_logger import logger


def handle_purchase_created(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase created handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "invoice_not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_CREATED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }


def handle_purchase_confirmed(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase confirmed handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase invoice_not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_CONFIRMED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }


def handle_purchase_deleted(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase deleted handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_DELETED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }

def handle_purchase_cancelled(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase cancel handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_CANCELED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }

def handle_purchase_reset_to_draft(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase cancel handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_CANCELED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }

def handle_purchase_approved(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase approval handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase invoice_not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_APPROVED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }

def handle_purchase_sent(event):

    try:
        purchase_id = event.get("purchase_id")

        if not purchase_id:
            logger.error("purchase_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_purchase_id"
            }

        purchase = PurchaseOrder.objects.get(id=purchase_id)

        logger.info(f"Purchase sent handled: {purchase.id}")

        return {
            "status": "success",
            "Purchase_id": purchase.id
        }

    except  PurchaseOrder.DoesNotExist:
        logger.error(f"purchase {purchase_id} not found during event handling")

        return {
            "status": "error",
            "reason": "purchase invoice_not_found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing PURCHASE_SENT event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }

def handle_shipment_confirmed(event):

    try:
        purchase_id = event.get("purchase_id")
        shipment_id = event.get("shipment_id")

        if not shipment_id:
            logger.error("shipment_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_shipment_id"
            }

        shipment = IncomingShipment.objects.get(id=shipment_id)

        logger.info(f"shipment confirmed handled: {shipment.id}")

        return {
            "status": "success",
            "shipment_id": shipment.id
        }

    except  IncomingShipment.DoesNotExist:
        logger.error(f"shipment {shipment_id} not found during event handling")

        return {
            "status": "error",
            "reason": "shipment not found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing SHIPMENT_CONFIRMED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }


def handle_shipment_cancelled(event):
    try:
        shipment_id = event.get("shipment_id")

        if not shipment_id:
            logger.error("shipment_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_shipment_id"
            }

        shipment = IncomingShipment.objects.get(id=shipment_id)

        logger.info(f"shipment cancel handled: {shipment.id}")

        return {
            "status": "success",
            "shipment_id": shipment.id
        }

    except  IncomingShipment.DoesNotExist:
        logger.error(f"shipment {shipment_id} not found during event handling")

        return {
            "status": "error",
            "reason": "shipment not found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing SHIPMENT_CANCELLED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }


def handle_shipment_received(event):
    try:
        shipment_id = event.get("shipment_id")

        if not shipment_id:
            logger.error("shipment_id missing from event payload")
            return {
                "status": "error",
                "reason": "missing_shipment_id"
            }

        shipment = IncomingShipment.objects.get(id=shipment_id)

        logger.info(f"shipment recieved handled: {shipment.id}")

        return {
            "status": "success",
            "shipment_id": shipment.id
        }

    except  IncomingShipment.DoesNotExist:
        logger.error(f"shipment {shipment_id} not found during event handling")

        return {
            "status": "error",
            "reason": "shipment not found"
        }

    except Exception as e:
        logger.exception(
            f"Error processing SHIPMENT_RECEIVED event: {e}"
        )

        return {
            "status": "error",
            "reason": "processing_failed"
        }
