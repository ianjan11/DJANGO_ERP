import logging
from django.db import transaction

from core.services.document_service.core.header_service import HeaderService
from core.services.document_service.core.item_service import ItemsService
from core.services.document_service.core.document_location_service import (
    DocumentItemLocationReconciliationService,
)
from core.services.document_service.core.payload_merge_service import DocumentPayloadMergeService
from core.utils.result import ok, fail

logger = logging.getLogger("document.sync")


class DocumentSyncError(Exception):
    """Raised when document sync fails with unrecoverable errors."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"Document sync failed: {errors}")


class DocumentSyncOrchestrator:
    """
    Generic orchestrator for synchronization of headers, item lines, and
    location reconciliation across multiple document types (Invoices, Orders, etc.).
    """

    # Maps document_type -> the header field name used to detect a location
    # change on that doc type. The resolved location *value* is supplied by
    # the caller per-call (see `location` param); this dict only gates which
    # doc types go through the location-aware branch, and names the field
    # to check in header_result["fields"] for change detection.
    LOCATION_FIELD_BY_DOC_TYPE = {
        "sales_order": "fulfillment_location",
    }

    def __init__(self):
        self.header_service         = HeaderService()
        self.item_service           = ItemsService()
        self.reconciliation_service = DocumentItemLocationReconciliationService()
        self.merge_service          = DocumentPayloadMergeService()
        logger.info("DocumentSyncOrchestrator initialized.")

    @transaction.atomic
    def sync_document(self, doc_instance, payload, location=None):
        """
        Main synchronization entrypoint. Accepts any document model instance
        (Invoice, SalesOrder, PurchaseOrder) and its structured payload.

        `location` is the already-resolved target location value for this
        sync (e.g. payload override or model default), supplied by the
        caller. It's only used for doc types registered in
        LOCATION_FIELD_BY_DOC_TYPE; ignored otherwise.
        """
        conn = transaction.get_connection()
        doc_type = payload.get("doc_type")

        if not doc_type:
            raise DocumentSyncError(["Missing 'document_type' in payload['meta']."])

        is_location_aware = doc_type in self.LOCATION_FIELD_BY_DOC_TYPE
        location_field = self.LOCATION_FIELD_BY_DOC_TYPE.get(doc_type)

        if is_location_aware:
            logger.info(
                "sync() entering for type '%s' [ID: %s] — location: %s, "
                "in atomic block: %s, savepoint depth: %s",
                doc_type,
                getattr(doc_instance, "id", "NEW"),
                location,
                conn.in_atomic_block,
                len(conn.savepoint_ids) if conn.in_atomic_block else 0,
            )

        # ------------------------------------------------------------------
        # 1. HEADER SYNC & CURRENCY CONVERSION CHECK
        # ------------------------------------------------------------------
        prev_currency_id = getattr(doc_instance, "currency_id", None)
        header_data = payload.get("header", {})
        updatable_fields = payload.get("updatable_fields", {})
        header_result = ok(changed=False, fields={}, invalid_fields=[])

        if header_data:
            header_result = self.header_service.update(
                source=doc_instance,
                data=header_data,
                updatable_fields=updatable_fields,
            )
            logger.info("Header sync result for %s: %s", doc_type, header_result)

            if header_result.get("errors"):
                raise DocumentSyncError(header_result["errors"])

            if header_result.get("changed"):
                doc_instance.save(update_fields=list(header_result["fields"].keys()))

            new_currency_id = getattr(doc_instance, "currency_id", None)
            company = getattr(doc_instance, "company", None)
            doc_date = self._get_document_date(doc_instance)


            currency_conversion = (
                (company, new_currency_id, doc_date)
                if prev_currency_id != new_currency_id and new_currency_id
                else None
            )
        else:
            currency_conversion = None

        # ------------------------------------------------------------------
        # 2. ITEM RESOLUTION (Location Change vs Row Mode vs Full Sync)
        # ------------------------------------------------------------------
        location_result = ok(deleted=[], remapped=[], constraints={})
        conflicts = []

        location_changed = is_location_aware and location_field in header_result.get("fields", {})

        if location_changed:
            clean_items = self._resolve_items_after_location_change(
                doc_instance=doc_instance,
                target_location=location,
                payload=payload,
                location_result=location_result,
                conflicts=conflicts,
            )
            logger.info(
                "Location change path (%s=%s): %d items resolved for %s",
                location_field,
                location,
                len(clean_items),
                doc_type,
            )

            if location_result.get("errors"):
                logger.warning(
                    "Location reconciliation errors on %s: %s",
                    doc_type,
                    location_result["errors"],
                )
                transaction.set_rollback(True)
                return fail(
                    errors=location_result["errors"],
                    header=header_result,
                    location=location_result,
                    items=ok(changed=False, created=[], updated=[], deleted=[]),
                    conflicts=conflicts,
                )

        elif payload.get("meta", {}).get("row_mode"):
            clean_items = self._extract_active_item(payload)
            logger.info("Row mode path: syncing prefix %s", payload["meta"].get("active_prefix"))

        else:
            clean_items = payload.get("items", [])
            logger.info("Full sync path: %d items", len(clean_items))

        # ------------------------------------------------------------------
        # 3. ITEM PERSISTENCE — runs for every path above (location-change,
        #    row-mode, or full-sync), for both location-aware and plain
        #    doc types. This was previously nested only inside the `else`
        #    branch, so location-change and row-mode paths fell through
        #    without persisting or returning — causing sync_document() to
        #    implicitly return None.
        # ------------------------------------------------------------------
        item_result = self.item_service.sync(
            items_data=clean_items,
            document_type=doc_type,
            doc_instance=doc_instance,
            currency_conversion=currency_conversion,
        )

        if item_result.get("row_errors"):
            logger.warning("Item sync row_errors on %s: %s", doc_type, item_result["row_errors"])
            transaction.set_rollback(True)
            return fail(
                errors=item_result["row_errors"],
                header=header_result,
                location=location_result,
                items=item_result,
                conflicts=conflicts,
            )

        return ok(
            header=header_result,
            location=location_result,
            items=item_result,
            conflicts=conflicts,
        )

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _resolve_items_after_location_change(self, doc_instance, target_location, payload, location_result, conflicts):
        reconciliation_data = self.reconciliation_service.reconcile(
            doc_instance=doc_instance,
            target_location=target_location,
        )
        location_result.update(reconciliation_data)

        merge_result = self.merge_service.merge(
            items_data=payload.get("items", []),
            reconciliation=location_result,
        )
        conflicts.extend(merge_result.get("conflicts", []))
        return merge_result.get("items", [])

    def _extract_active_item(self, payload):
        active_prefix = payload.get("meta", {}).get("active_prefix")

        if not active_prefix:
            raise DocumentSyncError(["row_mode=True but active_prefix is missing from meta."])

        for item in payload.get("items", []):
            if item.get("prefix") == active_prefix:
                return [item]

        raise DocumentSyncError([f"active_prefix '{active_prefix}' not found in payload items."])

    def _get_document_date(self, doc_instance):
        """Extracts date safely across different model field naming conventions."""
        for attr in ("date", "date_order", "issue_date", "created_at"):
            if hasattr(doc_instance, attr):
                return getattr(doc_instance, attr)
        return None