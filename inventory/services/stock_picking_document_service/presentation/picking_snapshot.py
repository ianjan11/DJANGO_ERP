import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("inventory.stock_picking.snapshot")


@dataclass
class StockPickingSnapshot:
    """
    Captures the state of a StockPicking transfer and its StockMove lines
    at a point in time for audit logs, diffing, and UI rendering plans.
    """

    # =====================================================
    # CORE ENTITY
    # =====================================================
    document: Any  # StockPicking instance

    # =====================================================
    # HEADER DIFF
    # =====================================================
    header_changes: Dict[str, Any] = field(default_factory=dict)
    header_changed: bool = False

    # =====================================================
    # ROW / LINE DIFF (StockMove changes)
    # =====================================================
    row_changes: Dict[str, Any] = field(
        default_factory=lambda: {
            "created": [],
            "updated": [],
            "deleted": [],
            "reordered": [],
        }
    )
    rows_changed: bool = False

    # =====================================================
    # VALIDATION & ERRORS
    # =====================================================
    validation: Dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True

    errors: Dict[str, Any] = field(default_factory=dict)
    row_errors: Dict[str, Any] = field(default_factory=dict)

    warnings: Dict[str, Any] = field(default_factory=dict)
    row_warnings: Dict[str, Any] = field(default_factory=dict)

    # =====================================================
    # STATE TRANSITION
    # =====================================================
    state_before: Optional[str] = None
    state_after: Optional[str] = None
    state_changed: bool = False

    # =====================================================
    # META (Debug / Audit)
    # =====================================================
    messages: List[str] = field(default_factory=list)

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def _read_state(picking) -> Optional[str]:
        """Safely extracts StockPicking status."""
        return getattr(picking, "status", getattr(picking, "state", None))

    # =====================================================
    # CAPTURE
    # =====================================================

    @classmethod
    def capture(cls, picking) -> "StockPickingSnapshot":
        """Capture the pre-mutation baseline state of a StockPicking."""
        snapshot = cls(document=picking)
        snapshot.state_before = cls._read_state(picking)
        return snapshot

    # =====================================================
    # DIFF
    # =====================================================

    @classmethod
    def diff(
        cls,
        snapshot_before: "StockPickingSnapshot",
        snapshot_after: "StockPickingSnapshot",
    ) -> Dict[str, Any]:
        """Calculate header, row, and status differences for stock pickings."""

        if not snapshot_before or not snapshot_after:
            return {
                "header_changed": False,
                "rows_changed": False,
                "state_changed": False,
                "any_changed": False,
                "changes": {},
            }

        state_before = snapshot_before.state_before
        state_after = snapshot_after.state_after or cls._read_state(snapshot_after.document)
        state_changed = state_before != state_after

        header_changed = (
            snapshot_after.header_changed
            or bool(snapshot_after.header_changes)
        )

        rows_changed = snapshot_after.rows_changed or any(
            bool(item_list)
            for item_list in snapshot_after.row_changes.values()
            if isinstance(item_list, list)
        )

        any_changed = header_changed or rows_changed or state_changed

        return {
            "header_changed": header_changed,
            "rows_changed": rows_changed,
            "state_changed": state_changed,
            "any_changed": any_changed,
            "changes": {
                "state": {
                    "before": state_before,
                    "after": state_after,
                    "changed": state_changed,
                },
                "header": snapshot_after.header_changes,
                "rows": snapshot_after.row_changes,
            },
        }

    # =====================================================
    # SERIALIZATION
    # =====================================================

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot state to a clean dictionary for HTMX UI triggers or logs."""
        return {
            "header_changes": self.header_changes,
            "header_changed": self.header_changed,
            "row_changes": self.row_changes,
            "rows_changed": self.rows_changed,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "state_changed": self.state_changed,
            "validation": self.validation,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "row_errors": self.row_errors,
            "warnings": self.warnings,
            "row_warnings": self.row_warnings,
            "messages": self.messages,
        }