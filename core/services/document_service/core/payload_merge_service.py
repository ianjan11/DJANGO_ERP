import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("document.merge")


class DocumentPayloadMergeService:
    """
    Applies reconciliation constraints to a user payload across document types
    (Invoices, Sales Orders, Purchase Orders, etc.).

    Responsibilities:
    - Apply deletion rules from location reconciliation
    - Remap quants when location changes
    - Clamp quantities to available stock
    - Preserve user intent where valid
    - Produce UI-friendly conflict metadata

    Does NOT:
    - Query the database
    - Decide reconciliation rules
    - Validate business availability logic
    """

    def merge(self, items_data, reconciliation):
        """
        Merge *items_data* (user payload) with *reconciliation* constraints.

        Returns:
            items     – merged item dicts ready for downstream sync.
            conflicts – list of conflict descriptors for UI feedback.
        """
        deleted_ids   = set(reconciliation.get("deleted",     []))
        constraints   = reconciliation.get("constraints",     {})

        merged         = []
        conflicts      = []
        user_item_ids  = set()

        for item_data in items_data:
            item_id = item_data.get("id")
            item_id = int(item_id) if item_id is not None else None

            # New rows have no ID — pass through without constraint checks
            if not item_id:
                merged.append(item_data)
                continue

            user_item_ids.add(item_id)

            # User explicitly deleted this row — respect it as-is
            if item_data.get("delete"):
                merged.append(item_data)
                continue

            # Reconciliation requires deletion (product unavailable at location)
            if item_id in deleted_ids:
                merged.append({**item_data, "delete": True})
                conflicts.append({
                    "item_id": item_id,
                    "reason":  "product_not_available_in_location",
                })
                continue

            constraint = constraints.get(item_id)

            # No constraint for this item — accept payload as-is
            if not constraint:
                merged.append(item_data)
                continue

            merged_item = dict(item_data)
            self._apply_quant_remap(merged_item, item_id, constraint, conflicts)
            self._apply_quantity_clamp(merged_item, item_id, item_data, constraint, conflicts)
            merged.append(merged_item)

        self._append_absent_deletions(deleted_ids, user_item_ids, merged, conflicts)

        return {"items": merged, "conflicts": conflicts}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_quant_remap(merged_item, item_id, constraint, conflicts):
        """Remap quant_id to the target location's quant, recording any change."""
        old_quant = merged_item.get("quant_id")
        new_quant = constraint["quant_id"]

        if old_quant != new_quant:
            conflicts.append({
                "item_id":      item_id,
                "reason":       "quant_remapped",
                "old_quant_id": old_quant,
                "new_quant_id": new_quant,
            })

        merged_item["quant_id"] = new_quant

    @staticmethod
    def _apply_quantity_clamp(merged_item, item_id, item_data, constraint, conflicts):
        """Clamp the requested quantity to available stock, recording any reduction."""
        user_qty = _to_decimal(item_data.get("quantity"))
        max_qty  = _to_decimal(constraint["max_quantity"])

        if user_qty > max_qty:
            conflicts.append({
                "item_id":   item_id,
                "reason":    "quantity_clamped",
                "requested": user_qty,
                "allowed":   max_qty,
            })

        merged_item["quantity"] = min(user_qty, max_qty)

    @staticmethod
    def _append_absent_deletions(deleted_ids, user_item_ids, merged, conflicts):
        """
        Force-delete reconciliation-removed items absent from the payload.

        These items weren't sent by the user (e.g. stale rows from a previous
        location) but still need to be explicitly deleted downstream.
        """
        for item_id in deleted_ids - user_item_ids:
            merged.append({"id": int(item_id), "delete": True})
            conflicts.append({
                "item_id": item_id,
                "reason":  "product_not_available_in_location",
            })


def _to_decimal(value) -> Decimal:
    """
    Safely coerce a value to Decimal.
    Treats None, empty string, and whitespace-only strings as zero.
    Returns zero on any conversion failure instead of crashing.
    """
    if value is None:
        return Decimal("0")

    stripped = str(value).strip()

    if not stripped:
        return Decimal("0")

    try:
        return Decimal(stripped)
    except InvalidOperation:
        return Decimal("0")