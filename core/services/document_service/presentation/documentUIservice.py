import logging
from typing import Any, Dict, List, Set

from core.services.document_service.presentation.snapshot import DocumentSnapshot

logger = logging.getLogger("document.services")


class DocumentUIService:
    """
    Builds HTMX swap and event-trigger instructions from DocumentSnapshot state.

    The service does not decide business logic. It only translates document
    changes and validation state into UI instructions.
    """

    PARTNER_FIELDS = {"partner"}
    DATE_FIELDS = {"issue_date", "due_date", "expected_date"}
    LOCATION_FIELDS = {"fulfillment_location"}
    CURRENCY_FIELDS = {"currency"}
    OTHER_FIELDS = {"payment_term, status, reference, notes"}

    def build_ui_plan(
        self,
        snapshot: DocumentSnapshot,
        dropped_unsaved_rows: bool = False,
        row_mode: bool = False,
    ) -> Dict[str, List[str]]:

        if not snapshot:
            return {"swap": [], "triggers": []}

        swap_targets: Set[str] = set()
        triggers: Set[str] = set()

        rows_changed = getattr(snapshot, "rows_changed", False)
        amounts_changed = getattr(snapshot, "amounts_changed", False)
        is_valid = getattr(snapshot, "is_valid", True)

        header_changes = getattr(snapshot, "header_changes", {}) or {}
        changed_fields = set(header_changes.keys())

        row_changes = getattr(snapshot, "row_changes", {}) or {}
        row_errors = getattr(snapshot, "row_errors", {}) or {}



        warnings = getattr(snapshot, "warnings", {}) or {}
        row_warnings = getattr(snapshot, "row_warnings", {}) or {}

        # ---------------------------------------------------------
        # Helpers
        # ---------------------------------------------------------

        def totals_resync():
            swap_targets.add("totals")

        def full_items_resync():
            """
            Re-render the complete items table (and its management form).

            Used when the current row cannot safely be represented by
            an outerHTML row swap. Totals always follow, since row
            content has changed.
            """
            swap_targets.add("items")
            totals_resync()

        def header_resync():
            swap_targets.add("header")

        # ---------------------------------------------------------
        # 1. HEADER CHANGES
        # ---------------------------------------------------------

        # Partner, dates, location and currency all re-render the header.
        # Currency also changes the symbol shown in totals.
        if (
            self.PARTNER_FIELDS
            | self.DATE_FIELDS
            | self.LOCATION_FIELDS
            | self.CURRENCY_FIELDS
            | self.OTHER_FIELDS
        ) & changed_fields:
            header_resync()


        if self.LOCATION_FIELDS & changed_fields:
            full_items_resync()
            totals_resync()

        
        if self.CURRENCY_FIELDS & changed_fields:
            full_items_resync()
            totals_resync()

        # ---------------------------------------------------------
        # 2. ROW / AMOUNT CHANGES
        # ---------------------------------------------------------

        if rows_changed or amounts_changed:
            totals_resync()

        # ---------------------------------------------------------
        # 3. ROW DELETIONS / LOCATION RECONCILIATION
        # ---------------------------------------------------------

        if row_changes.get("deleted"):
            full_items_resync()

        if "location_deleted_items" in row_errors:
            full_items_resync()

        # A newly created row that fails validation cannot be restored
        # by an individual row swap because the transaction rolls it back.
        if row_changes.get("created") and not row_mode:
            full_items_resync()

        # ---------------------------------------------------------
        # 4. VALIDATION ERRORS
        # ---------------------------------------------------------

        if not is_valid:
            triggers.add("showNotification")
            created_rows = row_changes.get("created") or []

            # Full document submission, or a new row that was rolled back:
            # rebuild the table so the UI reflects the database.
            # Single-row update on an existing row: the row itself is the
            # main response, so no items swap is needed.
            if not row_mode or created_rows:
                full_items_resync()


        if getattr(snapshot, "errors", None):
            header_resync()

        # ---------------------------------------------------------
        # 5. DROPPED UNSAVED ROWS
        # ---------------------------------------------------------

        if dropped_unsaved_rows and not row_mode:
            full_items_resync()

        # ---------------------------------------------------------
        # 6. WARNINGS
        # ---------------------------------------------------------

        if row_warnings or warnings:
            triggers.add("showNotification")

        if row_mode and "items" not in swap_targets:
            swap_targets.add("item-row")



        return {
            "swap": sorted(swap_targets),
            "triggers": sorted(triggers),
        }