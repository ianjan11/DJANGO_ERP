import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("document.snapshot")


@dataclass
class DocumentSnapshot:
    """
    Captures the state of any document (Invoice, Sales Order, Purchase Order, etc.)
    at a point in time to track changes across updates, perform diffing, and
    construct audit logs.

    `totals` is captured via CalculationService.recalculate() at snapshot time —
    once before mutation, once after — so diff() can tell whether the update
    actually moved the debit/credit totals, independent of which fields or rows
    caused it. This replaces the old totals_before/totals_after Decimal scalars:
    recalculate() already handles product-line vs. plain-line totals correctly,
    so there's no need to re-guess a total field name here.
    """

    # =====================================================
    # CORE ENTITY
    # =====================================================
    document: Any

    # =====================================================
    # TOTALS (for diffing amount changes — from CalculationService.recalculate())
    # =====================================================
    totals: Dict[str, Any] = field(default_factory=dict)

    amounts_changed: bool = False

    # =====================================================
    # HEADER DIFF
    # =====================================================
    header_changes: Dict[str, Any] = field(default_factory=dict)
    header_changed: bool = False

    # =====================================================
    # ROW / LINE DIFF
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
    # VALIDATION
    # =====================================================
    validation: Dict[str, Any] = field(default_factory=dict)
    is_valid: bool = True

    # =====================================================
    # STATE TRANSITION
    # =====================================================
    state_before: Optional[str] = None
    state_after: Optional[str] = None
    state_changed: bool = False

    # =====================================================
    # ERRORS
    # =====================================================
    errors: Dict[str, Any] = field(default_factory=dict)
    row_errors: Dict[str, Any] = field(default_factory=dict)

    # =====================================================
    # WARNINGS
    # =====================================================
    warnings: Dict[str, Any] = field(default_factory=dict)
    row_warnings: Dict[str, Any] = field(default_factory=dict)

    # =====================================================
    # META (debug / audit)
    # =====================================================
    messages: List[str] = field(default_factory=list)

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def _read_state(doc) -> Optional[str]:
        """Safely extract document status across models ('status', 'state', 'stage')."""
        return (
            getattr(doc, "status", None)
            or getattr(doc, "state", None)
            or getattr(doc, "stage", None)
        )

    # =====================================================
    # CAPTURE
    # =====================================================

    @classmethod
    def capture(cls, document, totals: Dict[str, Any] = None) -> "DocumentSnapshot":
        """
        Capture the current state of a document.

        `totals` should come from CalculationService.recalculate(document),
        called by the caller at the moment of capture (once before mutation,
        once after) — this method doesn't compute it itself, to avoid coupling
        the snapshot to the calculation service and to keep the "must be called
        while the DB transaction is clean" contract explicit at the call site.
        """
        snapshot = cls(document=document, totals=totals or {})
        snapshot.state_before = cls._read_state(document)
        return snapshot

    # =====================================================
    # DIFF
    # =====================================================

    @classmethod
    def diff(
        cls,
        snapshot_before: "DocumentSnapshot",
        snapshot_after: "DocumentSnapshot",
    ) -> Dict[str, Any]:
        """Calculate the difference between two document snapshots."""

        if not snapshot_before or not snapshot_after:
            return {
                "header_changed": False,
                "rows_changed": False,
                "state_changed": False,
                "amounts_changed": False,
                "any_changed": False,
                "changes": {},
            }

        # STATE
        state_before = snapshot_before.state_before
        state_after = snapshot_after.state_after or cls._read_state(snapshot_after.document)
        state_changed = state_before != state_after

        # TOTALS — sourced from CalculationService.recalculate(), not re-derived here
        totals_before = snapshot_before.totals or {}
        totals_after = snapshot_after.totals or {}

        amounts_changed = (
            totals_before.get("total_debit") != totals_after.get("total_debit")
            or totals_before.get("total_credit") != totals_after.get("total_credit")
        )

        # HEADER
        header_changed = (
            snapshot_after.header_changed
            or bool(snapshot_after.header_changes)
        )

        # ROWS
        rows_changed = snapshot_after.rows_changed or any(
            item
            for item_list in snapshot_after.row_changes.values()
            if isinstance(item_list, list)
            for item in item_list
        )

        return {
            "header_changed": header_changed,
            "rows_changed": rows_changed,
            "state_changed": state_changed,
            "amounts_changed": amounts_changed,
            # Fixed: v2 originally omitted amounts_changed here, so an
            # update that only moved debit/credit totals (no header/row/
            # state change recorded) would report any_changed=False.
            "any_changed": header_changed or rows_changed or state_changed or amounts_changed,
            "changes": {
                "state": {
                    "before": state_before,
                    "after": state_after,
                    "changed": state_changed,
                },
                "totals": {
                    "before": totals_before,
                    "after": totals_after,
                    "changed": amounts_changed,
                },
                "header": snapshot_after.header_changes,
                "rows": snapshot_after.row_changes,
            },
        }

    # =====================================================
    # SERIALISATION
    # =====================================================

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot metadata into a clean dictionary payload for audit logs or UI."""
        return {
            "header_changes": self.header_changes,
            "header_changed": self.header_changed,
            "row_changes": self.row_changes,
            "rows_changed": self.rows_changed,
            "totals": self.totals,
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