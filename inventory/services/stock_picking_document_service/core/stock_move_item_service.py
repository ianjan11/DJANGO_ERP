import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError, transaction

from core.services.document_service.field_normalize_service import FieldNormalizerService
from core.utils.result import fail, ok
from inventory.models import Product, StockMove, StockPicking, Uom

logger = logging.getLogger("inventory.stock_move")

normalizer = FieldNormalizerService()


class StockMoveItemsService:
    """
    Persistence layer dedicated exclusively to StockMove lines on a StockPicking.

    Provides a clean, atomic sync lifecycle with savepoint isolation per row
    so validation errors do not poison the entire batch.
    """

    UPDATABLE_FIELDS = {
        "product_id": int,
        "quantity": Decimal,
        "product_uom_id": int,
        "source_location_id": int,
        "dest_location_id": int,
    }

    # =========================================================================
    # PUBLIC SYNC PIPELINE
    # =========================================================================

    @transaction.atomic
    def sync(self, items_data: list, picking: StockPicking):
        """
        Synchronizes an array of move line payloads against a StockPicking instance.
        """
        if not picking:
            raise ValueError("StockMoveItemsService.sync requires a valid StockPicking instance.")

        # Resolve move lines relationship cleanly
        lines_rel = getattr(picking, "lines", getattr(picking, "move_lines", None))

        if lines_rel is None:
            lines_rel = StockMove.objects.filter(picking=picking).order_by("id")

        existing = {item.id: item for item in lines_rel.all()}
        created, updated, deleted, row_errors = [], [], [], {}

        for row in items_data:
            item_id = row.get("id")
            prefix = row.get("prefix") or f"items-{row.get('index', 0)}"

            # 1. New Line
            if not item_id:
                if self._truthy(row.get("delete")):
                    continue  # Unsaved row removed in UI
                self._handle_create(picking, row, prefix, created, row_errors)
                continue

            # 2. Existing Line
            item = existing.get(item_id)
            if not item:
                row_errors[prefix] = {"__all__": [f"Item {item_id} not found on this picking."]}
                continue

            # 3. Delete or Update
            if self._truthy(row.get("delete")):
                self._handle_delete(item, prefix, deleted, row_errors)
            else:
                self._handle_update(item, row, prefix, updated, row_errors, picking)

        if row_errors:
            transaction.set_rollback(True)
            return fail(
                row_errors=row_errors,
                changed=bool(created or updated or deleted),
                created=created,
                updated=updated,
                deleted=deleted,
            )

        return ok(
            changed=bool(created or updated or deleted),
            created=created,
            updated=updated,
            deleted=deleted,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)

    @staticmethod
    def _coerce(field_name: str, value: Any) -> Any:
        if value in (None, ""):
            return None
        target_type = StockMoveItemsService.UPDATABLE_FIELDS.get(field_name)
        if not target_type:
            return value
        try:
            if target_type is Decimal:
                return Decimal(str(value))
            return target_type(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _clear_relation_cache(item: StockMove, relation_name: str):
        """Clears Django related field cache when FK IDs are mutated."""
        try:
            field = item._meta.get_field(relation_name)
            field.get_cached_value(item)
            delattr(item, field.get_cache_name())
        except (AttributeError, KeyError, ObjectDoesNotExist):
            pass

    # =========================================================================
    # CRUD HANDLERS
    # =========================================================================

    def _handle_create(
        self,
        picking: StockPicking,
        row: dict,
        prefix: str,
        created: list,
        row_errors: dict,
    ):
        try:
            with transaction.atomic():
                item = self._create_item(picking, row)
                created.append(item.id)
        except ValidationError as exc:
            row_errors[prefix] = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": exc.messages}
        except (ValueError, TypeError, DatabaseError) as exc:
            logger.exception("Error creating stock move line for row %s", prefix)
            row_errors[prefix] = {"__all__": [str(exc)]}

    def _handle_update(
        self,
        item: StockMove,
        row: dict,
        prefix: str,
        updated: list,
        row_errors: dict,
        picking: StockPicking,
    ):
        try:
            with transaction.atomic():
                changes = self._update_item(item, row, picking)
                if changes:
                    updated.append({"id": item.id, "changes": changes})
        except ValidationError as exc:
            row_errors[prefix] = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": exc.messages}
        except (ValueError, TypeError, DatabaseError) as exc:
            logger.exception("Error updating stock move line for row %s", prefix)
            row_errors[prefix] = {"__all__": [str(exc)]}

    def _handle_delete(self, item: StockMove, prefix: str, deleted: list, row_errors: dict):
        try:
            with transaction.atomic():
                item_id = item.id
                item.delete()
                deleted.append(item_id)
        except Exception as exc:
            row_errors[prefix] = {"__all__": [str(exc)]}

    # =========================================================================
    # LINE CREATION / UPDATE
    # =========================================================================

    def _create_item(self, picking: StockPicking, data: dict) -> StockMove:
        item = StockMove(picking=picking)

        # 1. Apply fields
        self._apply_fields(item, data)

        # 2. Location fallbacks
        if not item.source_location_id and getattr(picking, "source_location_id", None):
            item.source_location_id = picking.source_location_id

        if not item.dest_location_id and getattr(picking, "dest_location_id", None):
            item.dest_location_id = picking.dest_location_id

        # 3. Load product explicitly to avoid RelatedObjectDoesNotExist on item.product
        product = None
        if item.product_id:
            product = self._validate_product(picking, item.product_id)
            if not item.product_uom_id and product:
                item.product_uom_id = product.uom_id

        # 4. Check UoM compatibility against loaded product instance
        self._check_uom(product, item.product_uom_id)

        item.full_clean()
        item.save()
        item.refresh_from_db()
        return item


    def _update_item(self, item: StockMove, data: dict, picking: StockPicking) -> dict:
        changes = {}
        product_changed = False

        for field in self.UPDATABLE_FIELDS:
            # Match payload key variations (e.g. source_location vs source_location_id)
            payload_key = field
            if field not in data and field.endswith("_id"):
                alt_key = field[:-3]
                if alt_key in data:
                    payload_key = alt_key

            if payload_key not in data:
                continue

            old = getattr(item, field, None)
            new = self._coerce(field, data[payload_key])

            if old != new:
                setattr(item, field, new)
                changes[field] = {"old": old, "new": new}
                if field == "product_id":
                    product_changed = True

        # Clear cached relationships if foreign keys mutated
        if product_changed:
            self._clear_relation_cache(item, "product")
        if product_changed or "product_uom_id" in changes:
            self._clear_relation_cache(item, "product_uom")

        # Re-resolve default UoM if product changed and payload omitted explicit UoM
        if product_changed and "product_uom_id" not in data and "product_uom" not in data:
            if item.product_id and hasattr(item, "product") and item.product:
                old_uom = item.product_uom_id
                item.product_uom = item.product.uom
                if old_uom != item.product_uom_id:
                    changes["product_uom_id"] = {"old": old_uom, "new": item.product_uom_id}

        # Fallback location checks on update if explicit nulls were set
        if not item.source_location_id and getattr(picking, "source_location_id", None):
            item.source_location_id = picking.source_location_id
        if not item.dest_location_id and getattr(picking, "dest_location_id", None):
            item.dest_location_id = picking.dest_location_id

        if product_changed and item.product_id:
            self._validate_product(picking, item.product_id)

        if item.product_id and item.product_uom_id:
            self._check_uom(item.product, item.product_uom_id)

        if changes:
            item.full_clean()
            item.save()
            item.refresh_from_db()

        return changes

    # =========================================================================
    # INTERNAL FIELD & VALIDATION HELPERS
    # =========================================================================

    def _apply_fields(self, item: StockMove, data: dict):
        """Map payload dictionary onto StockMove instance fields."""
        for field in self.UPDATABLE_FIELDS:
            payload_key = field
            if field not in data and field.endswith("_id"):
                alt_key = field[:-3]
                if alt_key in data:
                    payload_key = alt_key

            if payload_key in data:
                val = self._coerce(field, data[payload_key])
                setattr(item, field, val)

    @staticmethod
    def _validate_product(picking: StockPicking, product_id: int) -> Optional[Product]:
        """Ensures the product is stockable/consumable and valid for the company context."""
        if not product_id:
            return None
        qs = Product.objects.select_related("uom").filter(
            pk=product_id,
            product_type__in=("storable", "consumable"),
        )
        company_id = getattr(picking, "company_id", None)
        if company_id:
            qs = qs.filter(company_id=company_id)

        product = qs.first()
        if not product:
            raise ValidationError({"product": ["Selected product is invalid or unavailable."]})
        return product

    @staticmethod
    def _check_uom(product: Optional[Product], uom_id: Optional[int]):
        """Validates that the selected UoM belongs to the same UoM Category as the product."""
        if not product or not uom_id or not product.uom_id:
            return
        uom = Uom.objects.only("category_id").filter(pk=uom_id).first()
        if not uom:
            raise ValidationError({"product_uom": ["Selected UoM does not exist."]})
        if uom.category_id != product.uom.category_id:
            raise ValidationError(
                {"product_uom": ["The selected UoM is incompatible with the product."]}
            )