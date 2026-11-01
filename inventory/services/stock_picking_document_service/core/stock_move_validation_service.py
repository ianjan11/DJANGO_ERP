import logging
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Sum

from inventory.models import (
    StockLocation,
    StockMove,
    StockPicking,
    StockPickingType,
)

logger = logging.getLogger("inventory.stock_picking")

ZERO = Decimal("0")


class StockPickingValidationService:
    """
    Validation engine for StockPicking transfers and demand lines (StockMove):
    header integrity, structural line rules, and return bounds.

    Stock availability is deliberately NOT validated (Odoo-style permissive
    inventory). A picking can demand more than is on hand; shortages surface
    through reservation state (CONFIRMED / PARTIALLY_AVAILABLE) and, at
    completion, as negative quants, never as a document-editing error.

    Returns standard result dicts compatible with `_collect`:
        {
            "errors": {field: [msgs]},
            "warnings": {field: [msgs]},
            "row_errors": {index: {field: [msgs]}},
            "row_warnings": {index: {field: [msgs]}},
        }
    """

    EDITABLE_STATUSES = {StockPicking.Status.DRAFT, "draft"}

    # =====================================================
    # PUBLIC ENTRY POINT
    # =====================================================

    def validate_picking(self, picking: StockPicking, lines=None) -> dict:
        """
        Validates picking header, structural line rules and return bounds.

        lines : Iterable of StockMove instances (unsaved formset lines or DB models).
        """
        lines = list(self._get_lines(picking) if lines is None else lines)

        errors: dict = {}
        warnings: dict = {}
        row_errors: dict = {}
        row_warnings: dict = {}

        # 1. Header Validation
        self._validate_header(picking, lines, errors, warnings)

        # 2. Structural Line Validation
        for idx, move in enumerate(lines):
            line_errs = self._validate_line(move, picking)
            if line_errs:
                row_errors[idx] = line_errs

        # 3. Return Validation (Prevent over-returning fulfilled demand)
        if getattr(picking.picking_type, "code", None) == StockPickingType.Code.RETURN:
            self._validate_returns(lines, row_errors)

        return {
            "errors": errors,
            "warnings": warnings,
            "row_errors": row_errors,
            "row_warnings": row_warnings,
        }

    # =====================================================
    # 1. HEADER VALIDATION
    # =====================================================

    def _validate_header(self, picking: StockPicking, lines, errors, warnings):
        status = getattr(picking, "status", None)
        if status and str(status) not in self.EDITABLE_STATUSES:
            errors["status"] = [f"Picking '{picking}' is in status '{status}' and cannot be modified."]

        picking_type = getattr(picking, "picking_type", None)
        if picking_type is None:
            errors["picking_type"] = ["Operation type is required."]

        if picking_type and getattr(picking_type, "partner_required", False):
            if not getattr(picking, "partner_id", None):
                errors["partner"] = ["Partner is required for this operation type."]

        source = getattr(picking, "source_location", None)
        dest = getattr(picking, "dest_location", None)

        if not source:
            errors["source_location"] = ["Source location is required."]
        if not dest:
            errors["dest_location"] = ["Destination location is required."]

        if source and dest:
            if source.id == dest.id:
                errors["dest_location"] = ["Source and destination locations must differ."]
            if source.usage == StockLocation.Usage.VIEW:
                errors["source_location"] = [f"View location '{source.complete_name}' cannot be used as source."]
            if dest.usage == StockLocation.Usage.VIEW:
                errors["dest_location"] = [f"View location '{dest.complete_name}' cannot be used as destination."]

        scheduled = getattr(picking, "scheduled_date", None)
        if scheduled is not None and not isinstance(scheduled, (date, datetime)):
            errors["scheduled_date"] = ["Enter a valid scheduled date."]

    # =====================================================
    # 2. LINE VALIDATION
    # =====================================================

    def _validate_line(self, move: StockMove, picking: StockPicking) -> dict:
        line_errors = {}

        product = getattr(move, "product", None)
        if product is None:
            line_errors["product"] = ["Product is required."]
            return line_errors

        if hasattr(product, "is_stockable") and not product.is_stockable:
            line_errors["product"] = [
                f"'{product.name}' is a "
                f"{product.get_product_type_display() if hasattr(product, 'get_product_type_display') else 'non-storable'}"
                " product and cannot appear in a stock move."
            ]

        qty = getattr(move, "quantity", None)
        if qty is None or qty <= ZERO:
            line_errors["quantity"] = ["Quantity must be greater than zero."]

        uom = getattr(move, "product_uom", None) or getattr(product, "uom", None)
        product_uom = getattr(product, "uom", None)
        if uom and product_uom and getattr(uom, "category_id", None) != getattr(product_uom, "category_id", None):
            line_errors["product_uom"] = [
                f"UoM '{uom.name}' is incompatible with product storage UoM '{product_uom.name}'."
            ]

        src = getattr(move, "source_location", None) or picking.source_location
        dst = getattr(move, "dest_location", None) or picking.dest_location

        if src and dst and src.id == dst.id:
            line_errors["dest_location"] = ["Source and destination locations must differ."]

        tracking = getattr(product, "tracking", "none")
        lot = getattr(move, "lot", None)

        if tracking in ("lot", "serial") and not lot:
            line_errors["lot"] = [f"Product '{product.name}' is tracked by {tracking}: a lot/serial number is required."]
        elif tracking == "none" and lot:
            line_errors["lot"] = [f"Product '{product.name}' is not tracked, so a lot/serial number cannot be assigned."]

        return line_errors

    # =====================================================
    # 3. RETURN VALIDATION
    # =====================================================

    def _validate_returns(self, lines, row_errors):
        """Validates return bounds against completed quantities on linked lines."""
        for idx, move in enumerate(lines):
            qty = getattr(move, "quantity", ZERO) or ZERO
            if qty <= ZERO:
                continue

            max_returnable = None
            origin_ref = ""

            if move.sale_line_id:
                completed_qty = StockMove.objects.filter(
                    sale_line_id=move.sale_line_id,
                    status=StockMove.Status.COMPLETED,
                ).aggregate(total=Sum("quantity"))["total"] or ZERO

                max_returnable = completed_qty
                origin_ref = f"Sales Line #{move.sale_line_id}"

            elif move.purchase_line_id:
                completed_qty = StockMove.objects.filter(
                    purchase_line_id=move.purchase_line_id,
                    status=StockMove.Status.COMPLETED,
                ).aggregate(total=Sum("quantity"))["total"] or ZERO

                max_returnable = completed_qty
                origin_ref = f"Purchase Line #{move.purchase_line_id}"

            if max_returnable is not None and qty > max_returnable:
                row_errors.setdefault(idx, {}).setdefault("quantity", []).append(
                    f"Return quantity ({qty}) exceeds total completed quantity ({max_returnable}) for {origin_ref}."
                )

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def _get_lines(picking: StockPicking):
        return (
            StockMove.objects.filter(picking=picking)
            .select_related("product__uom", "product_uom")
            .order_by("id")
        )