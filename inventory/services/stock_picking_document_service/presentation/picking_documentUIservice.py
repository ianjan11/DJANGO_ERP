import logging
from typing import Dict, List, Set
from inventory.services.stock_picking_document_service.presentation.picking_snapshot import StockPickingSnapshot

logger = logging.getLogger("document.services")

class DocumentUIService:
    """
    Builds HTMX swap and event-trigger instructions from DocumentSnapshot state
    for the StockPicking screen (header + move lines).

    The service does not decide business logic. It only translates document
    changes and validation state into UI instructions.

    Swap targets: "header", "items", "item-row".
    """

    PARTNER_FIELDS = {"partner"}
    DATE_FIELDS = {"scheduled_date"}
    OTHER_FIELDS = {"origin"}

    # Lines inherit blank source/dest from the picking, so these change what
    # every row displays.
    LOCATION_FIELDS = {"source_location", "dest_location"}

    # Changes partner requirement and which lines get stock-availability warnings.
    PICKING_TYPE_FIELDS = {"picking_type"}

    HEADER_FIELDS = (
        PARTNER_FIELDS | DATE_FIELDS | OTHER_FIELDS | LOCATION_FIELDS | PICKING_TYPE_FIELDS
    )
    ITEMS_RESYNC_FIELDS = LOCATION_FIELDS | PICKING_TYPE_FIELDS


    def build_ui_plan(
        self,
        snapshot: StockPickingSnapshot,
        dropped_unsaved_rows: bool = False,
        row_mode: bool = False,
    ) -> Dict[str, List[str]]:

        if not snapshot:
            return {"swap": [], "triggers": []}

        swap_targets: Set[str] = set()
        triggers: Set[str] = set()

        is_valid = getattr(snapshot, "is_valid", True)
        changed_fields = set((getattr(snapshot, "header_changes", None) or {}).keys())
        row_changes = getattr(snapshot, "row_changes", None) or {}
        warnings = getattr(snapshot, "warnings", None) or {}
        row_warnings = getattr(snapshot, "row_warnings", None) or {}

        created_rows = row_changes.get("created") or []


        def full_items_resync():
            """Re-render the whole items table (and management form)."""
            swap_targets.add("items")

        # 1. HEADER CHANGES
        if self.HEADER_FIELDS & changed_fields:
            swap_targets.add("header")

        if self.ITEMS_RESYNC_FIELDS & changed_fields:
            full_items_resync()

        # 2. ROW DELETIONS / ROLLED-BACK CREATES
        if row_changes.get("deleted"):
            full_items_resync()

        # A new row cannot be restored by a single-row swap when validation
        # rolls the transaction back, so rebuild the table.
        if created_rows and not row_mode:
            full_items_resync()

        # 3. VALIDATION ERRORS
        if not is_valid:
            triggers.add("showNotification")

            # Full submission, or a new row that was rolled back: rebuild from DB.
            # Single existing-row update: the row itself is the response.
            if not row_mode or created_rows:
                full_items_resync()

        if getattr(snapshot, "errors", None):
            swap_targets.add("header")

        # 4. DROPPED UNSAVED ROWS
        if dropped_unsaved_rows and not row_mode:
            full_items_resync()

        # 5. WARNINGS
        if row_warnings or warnings:
            triggers.add("showNotification")

        # 6. DEFAULT: in row mode the row is always the main response
        if row_mode and "items" not in swap_targets:
            swap_targets.add("item-row")

        return {
            "swap": sorted(swap_targets),
            "triggers": sorted(triggers),
        }