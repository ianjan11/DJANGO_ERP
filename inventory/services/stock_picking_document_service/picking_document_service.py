import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.forms.utils import ErrorDict, ErrorList

from inventory.forms.stock_operation_form import StockMoveFormSet, StockPickingHeaderForm
from inventory.models import StockPicking, StockMove
from inventory.services.stock_picking_document_service.core.picking_move_header_service import HeaderService
from inventory.services.stock_picking_document_service.core.picking_payload_builder import build_outgoing_context
from inventory.services.stock_picking_document_service.core.stock_move_item_service import StockMoveItemsService
from inventory.services.stock_picking_document_service.core.stock_move_validation_service import (
    StockPickingValidationService,
)
from inventory.services.stock_picking_document_service.presentation.picking_documentUIservice import DocumentUIService
from inventory.services.stock_picking_document_service.presentation.picking_snapshot import StockPickingSnapshot

logger = logging.getLogger("sales.invoice")


class DocumentService:
    """
    Application service for managing StockPicking transfers and StockMove demand lines.

    Pipeline Execution:
        1. Edit-Lock Guard Check
        2. Capture Baseline Pre-Mutation Snapshot
        3. Sync Header & StockMove Lines (in-memory & atomic DB state)
        4. Run Validation (Header + Lines + Returns + Stock Levels)
        5. Capture Post-Operation Snapshot & Diff
        6. Construct HTMX UI Plan
        7. Bind & Inject Errors into Header Form and Line Formset
        8. Commit Transaction or Trigger Atomic Rollback
    """

    def __init__(self):
        self.header_service = HeaderService()
        self.item_service = StockMoveItemsService()
        self.validation_service = StockPickingValidationService()
        self.ui_service = DocumentUIService()

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _is_editable(picking: StockPicking) -> bool:
        """Determines if the transfer is in an editable state (e.g. PENDING or draft)."""
        status = getattr(picking, "status", None)
        return not status or str(status) in StockPickingValidationService.EDITABLE_STATUSES

    @staticmethod
    def _collect(target: dict, result: dict, key: str = "errors") -> None:
        """
        Merges flat errors/warnings or list-indexed row errors from service results.

        errors     shape: { field: ["msg"] }
        row_errors shape: { index_or_prefix: { field: ["msg"] } }
        """
        if key in ("row_errors", "row_warnings"):
            for prefix, field_errors in (result.get(key) or {}).items():
                if not isinstance(field_errors, dict):
                    continue
                bucket = target.setdefault(prefix, {})
                for field, msgs in field_errors.items():
                    bucket.setdefault(field, []).extend(msgs)
        else:
            for field, messages in (result.get(key) or {}).items():
                target.setdefault(field, []).extend(messages)

    def _build_fail_payload(self, picking: StockPicking, errors: dict) -> dict:
        """Constructs a minimal, valid payload structure for hard failures (locked transfers)."""
        snapshot = SimpleNamespace(
            errors=errors,
            row_errors={},
            warnings={},
            row_warnings={},
            is_valid=False,
            rows_changed=False,
            header_changed=False,
            header_changes={},
        )
        return build_outgoing_context(
            picking=picking,
            snapshot=snapshot,
            ui_plan={"swap": [], "triggers": ["show-validation-toast"]},
            diff={},
            header={},
            items={},
            validation={"errors": errors, "row_errors": {}},
            forms=None,
            header_form=None,
        )

    # =========================================================
    # FORM BINDING & ERROR INJECTION
    # =========================================================

    def _build_header_form(self, picking: StockPicking, request: Optional[Any], errors: dict):
        """Builds the header ModelForm and layers service-level errors on top of form errors."""
        company = getattr(request, "company", None) if request else None

        if request is not None and request.method == "POST" and errors:
            form = StockPickingHeaderForm(request.POST, instance=picking, company=company)
            form.is_valid()
        else:
            form = StockPickingHeaderForm(instance=picking, company=company)

        if not errors:
            return form

        if form._errors is None:
            form._errors = ErrorDict()

        for field, messages in errors.items():
            msgs = messages if isinstance(messages, list) else [messages]
            if field in form._errors:
                form._errors[field].extend(msgs)
            else:
                form._errors[field] = ErrorList(msgs)

        return form

    def _build_forms(self, picking: StockPicking, request: Optional[Any], row_errors: dict):
        """Rebuilds the StockMove FormSet and injects service-layer errors directly into lines."""
        forms = StockMoveFormSet(
            instance=picking,
            prefix="items",
            queryset=StockMove.objects.filter(picking=picking).order_by("id"),
            form_kwargs={
                "company": request.company,
                "picking": picking,
                "picking_status": picking.status,
            },
        )

        if row_errors and request and request.method == "POST":
            row_prefix = request.POST.get("row_prefix")

            if row_prefix:
                for form in forms:
                    if getattr(form, "prefix", None) == row_prefix:
                        form.data = request.POST
                        form.is_bound = True
                        form.full_clean()
                        break

        for form in forms:
            if not form.instance or not form.instance.pk:
                continue

            fields_with_errors = row_errors.get(
                form.prefix
            ) or row_errors.get(str(form.instance.pk))

            if not isinstance(fields_with_errors, dict):
                continue

            if form._errors is None:
                form._errors = ErrorDict()

            if not hasattr(form, "cleaned_data"):
                form.cleaned_data = {}

            for field, messages in fields_with_errors.items():
                msgs = messages if isinstance(messages, list) else [messages]
                if field in form._errors:
                    form._errors[field].extend(msgs)
                else:
                    form._errors[field] = ErrorList(msgs)

        return forms

    # =========================================================
    # MAIN TRANSACTION PIPELINE
    # =========================================================

    @transaction.atomic
    def apply_state(
        self,
        picking: StockPicking,
        payload: dict,
        request: Optional[Any] = None,
        dropped_unsaved_rows: bool = False,
    ) -> dict:


        dropped_unsaved_rows = dropped_unsaved_rows or payload.get("dropped_unsaved_rows", False)
        row_mode = (payload.get("meta") or {}).get("row_mode", False)

        errors: dict = {}
        row_errors: dict = {}
        warnings: dict = {}
        row_warnings: dict = {}

        # 1. EDIT-LOCK GUARD
        if not self._is_editable(picking):
            return self._build_fail_payload(
                picking, {"document": ["This transfer is locked and cannot be edited."]}
            )

        # 2. PRE-MUTATION SNAPSHOT BASELINE
        snapshot_before = StockPickingSnapshot.capture(picking)

        # 3. SYNC HEADER AND ITEMS
        header_result = self.header_service.update(
            picking,
            payload.get("header") or {},
            payload.get("updatable_fields") or {},
        ) or {}
        items_result = self.item_service.sync(payload.get("items") or [], picking) or {}

        logger.debug('item-results: %s', items_result)

        self._collect(errors, header_result, "errors")
        self._collect(row_errors, items_result, "row_errors")

        logger.debug("After sync - errors: %s | row_errors: %s", errors, row_errors)

        # 4. VALIDATION ENGINE
        lines = list(
            StockMove.objects.filter(picking=picking)
            .select_related("product__uom", "product_uom")
            .order_by("id")
        )
        validation_result = self.validation_service.validate_picking(picking, lines=lines)

        self._collect(errors, validation_result, "errors")
        self._collect(warnings, validation_result, "warnings")
        self._collect(row_errors, validation_result, "row_errors")
        self._collect(row_warnings, validation_result, "row_warnings")

        # 5. POST-OPERATION SNAPSHOT & DIFF
        snapshot_after = StockPickingSnapshot(document=picking)
        snapshot_after.state_before = snapshot_before.state_before
        snapshot_after.state_after = StockPickingSnapshot._read_state(picking)
        snapshot_after.header_changed = header_result.get("changed", False)
        snapshot_after.header_changes = header_result.get("fields", {})
        snapshot_after.rows_changed = items_result.get("changed", False)
        snapshot_after.row_changes = {
            "created": items_result.get("created", []),
            "updated": items_result.get("updated", []),
            "deleted": items_result.get("deleted", []),
            "reordered": [],
        }
        snapshot_after.errors = errors
        snapshot_after.row_errors = row_errors
        snapshot_after.is_valid = not errors and not row_errors
        snapshot_after.warnings = warnings
        snapshot_after.row_warnings = row_warnings

        diff = StockPickingSnapshot.diff(snapshot_before, snapshot_after)
        snapshot_after.state_changed = diff["state_changed"]

        # 6. GENERATE UI PLAN
        ui_plan = self.ui_service.build_ui_plan(
            snapshot=snapshot_after,
            dropped_unsaved_rows=dropped_unsaved_rows,
            row_mode=row_mode,
        )
        logger.info("UI plan built: %s", ui_plan)

        # 7. BUILD BOUND FORMS BEFORE ROLLBACK CHECK
        forms = self._build_forms(picking, request, row_errors)
        header_form = self._build_header_form(picking, request, errors)

        # 8. TRANSACTION COMMIT OR ROLLBACK
        if not errors and not row_errors:
            try:
                picking.save()
                picking.refresh_from_db()

                forms = self._build_forms(picking, request, row_errors)
                header_form = self._build_header_form(picking, request, errors)
                logger.info("StockPicking pk=%s saved successfully.", picking.pk)

            except Exception as exc:
                logger.exception("StockPicking save failed: %s", exc)
                errors["save"] = [str(exc)]
                snapshot_after.errors = errors
                snapshot_after.is_valid = False
                transaction.set_rollback(True)
        else:
            transaction.set_rollback(True)
            logger.warning(
                "Transaction rolled back - errors=%s | row_errors=%s", errors, row_errors
            )

        return build_outgoing_context(
            picking=picking,
            snapshot=snapshot_after,
            ui_plan=ui_plan,
            diff=diff,
            header=header_result,
            items=items_result,
            validation=validation_result,
            forms=forms,
            header_form=header_form,

        )