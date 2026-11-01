import logging
from decimal import Decimal

from inventory.models import StockQuant
from core.utils.result import ok, fail

logger = logging.getLogger("document.reconciliation")


class DocumentItemLocationReconciliationService:
    """
    Read-only service.

    Determines how document line items map to stock quants at a target location,
    scoped to the document's company. Works for Invoices, Sales Orders, and any
    model with product-based lines.

    Assumes StockQuant uniqueness of (product, location, company).
    """

    def __init__(self):
        logger.info("DocumentItemLocationReconciliationService initialized.")

    def reconcile(self, doc_instance, target_location):
        """
        Map each line item to a quant at *target_location* for the document's company.

        Returns:
            deleted     – item IDs with no matching quant at the target location.
            remapped    – items whose quant changes (old/new quant IDs).
            constraints – {item_id: {quant_id, max_quantity}} for surviving items.
            errors      – {item_id: ["message"]} for unexpected exceptions.
        """
        if not target_location:
            return ok(deleted=[], remapped=[], constraints={})

        company = getattr(doc_instance, "company", None)
        if not company:
            raise AttributeError(
                f"Model '{type(doc_instance).__name__}' has no 'company' — "
                "required to scope quant lookup, since quants are unique per "
                "(product, location, company)."
            )

        lines_rel = getattr(doc_instance, "lines", getattr(doc_instance, "items", None))
        if lines_rel is None:
            raise AttributeError(
                f"Model '{type(doc_instance).__name__}' has neither 'lines' nor 'items' relationship."
            )

        items = list(lines_rel.select_related("product"))
        if not items:
            return ok(deleted=[], remapped=[], constraints={})

        quant_map = self._build_quant_map(items, target_location, company)
        deleted = []
        remapped = []
        constraints = {}
        errors = {}

        for item in items:
            try:
                self._reconcile_item(item, quant_map, deleted, remapped, constraints)
            except Exception as exc:
                logger.exception("Error reconciling item %s", getattr(item, "id", None))
                errors[str(getattr(item, "id", "unknown"))] = [str(exc)]

        if errors:
            return fail(
                errors=errors,
                deleted=deleted,
                remapped=remapped,
                constraints=constraints,
            )

        return ok(deleted=deleted, remapped=remapped, constraints=constraints)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_quant_map(items, target_location, company):
        """
        Returns {product_id: StockQuant} at *target_location* for *company*.
        Since (product, location, company) is unique, this is safe — no risk
        of one product silently overwriting another's quant in the dict.
        """
        product_ids = set()
        for item in items:
            prod_id = getattr(item, "product_id", None)
            if not prod_id and getattr(item, "quant", None):
                prod_id = item.quant.product_id
            if prod_id:
                product_ids.add(prod_id)

        if not product_ids:
            return {}

        quants = StockQuant.objects.filter(
            location=target_location,
            company=company,
            product_id__in=product_ids,
        )

        return {quant.product_id: quant for quant in quants}

    @staticmethod
    def _reconcile_item(item, quant_map, deleted, remapped, constraints):
        """
        Classifies a single item based on target location stock availability.
        """
        product_id = getattr(item, "product_id", None)
        current_quant = getattr(item, "quant", None)

        if not product_id and current_quant:
            product_id = current_quant.product_id

        # Item has no product attached at all -> mark for deletion
        if not product_id:
            deleted.append(item.id)
            return

        target_quant = quant_map.get(product_id)

        # No stock quant exists for this product at the new target location/company
        if target_quant is None:
            deleted.append(item.id)
            return

        current_quant_id = current_quant.id if current_quant else None
        if current_quant_id != target_quant.id:
            remapped.append({
                "item_id": item.id,
                "old_quant_id": current_quant_id,
                "new_quant_id": target_quant.id,
            })

        constraints[item.id] = {
            "quant_id": target_quant.id,
            "max_quantity": (
                target_quant.quantity
                if target_quant.quantity is not None
                else Decimal("0")
            ),
        }