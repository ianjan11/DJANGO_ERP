import logging
from types import SimpleNamespace
from typing import Any, Optional
from django.db import transaction
from django.forms.utils import ErrorDict, ErrorList

from accounting.models import AccountMove
from accounting.services.invoice.invoice_state_service import InvoiceStateService
from core.services.document_service.core.calculation_service import CalculationService
from core.services.document_service.presentation.snapshot import DocumentSnapshot
from core.services.document_service.core.header_service import HeaderService
from core.services.document_service.core.item_service import ItemsService
from core.services.document_service.core.document_location_service import DocumentItemLocationReconciliationService
from core.services.document_service.core.document_orchestrator import DocumentSyncOrchestrator
from core.services.document_service.core.payload_builder import build_outgoing_context
from core.services.document_service.presentation.documentUIservice import DocumentUIService
from core.services.document_service.core.validation_service import DocumentValidationService
from core.services.document_service.presentation.htmx_swap_service import UIResponseService
from inventory.models import Product
from purchases.models import PurchaseOrder
from purchases.services.purchase_state_service import PurchaseOrdersStateService
from sales.models import SalesOrder
from sales.services.sales_order_service.sales_order_state_service import SalesOrdersStateService

logger = logging.getLogger("sales.invoice")


class DocumentService:
    """
    Unified high-level application service that coordinates transactional updates,
    calculations, validation, snapshot diffing, and presentation context across
    all document models (Sales Orders, Invoices, Purchase Orders, etc.).
    """

    def __init__(self):
        self.invoice_state_service = InvoiceStateService()
        self.sales_state_service = SalesOrdersStateService()
        self.purchase_state_service = PurchaseOrdersStateService()

        # doc_type -> StateService. "invoice" covers all invoice variants,
        # not just sales-originated ones.
        self.state_service_registry = {
            "sales_invoice": self.invoice_state_service,
            "supplier_invoice": self.invoice_state_service,
            "sales_order": self.sales_state_service,
            "purchase_order": self.purchase_state_service,
            "entry": self.invoice_state_service,
        }

        self.header_service = HeaderService()
        self.item_service = ItemsService()
        self.location_service = DocumentItemLocationReconciliationService
        self.calculation_service = CalculationService()
        self.validation_service = DocumentValidationService()
        self.sync_orchestrator = DocumentSyncOrchestrator()

        self.ui_service = DocumentUIService()
        self.swap_service = UIResponseService

    # =========================================================
    # HELPERS
    # =========================================================
    def _collect(self, target: dict, result: dict, key: str = "errors") -> None:
        """
        Merge errors from service results into the unified error payload.

        errors     shape: { field: ["msg"] }              — flat, one level
        row_errors shape: { prefix: { field: ["msg"] } } — two levels
        """
        if key == "row_errors":
            for prefix, field_errors in (result.get(key) or {}).items():
                if not isinstance(field_errors, dict):
                    continue  # skip structural keys like location_deleted_items
                if prefix in target:
                    for field, msgs in field_errors.items():
                        if field in target[prefix]:
                            target[prefix][field].extend(msgs)
                        else:
                            target[prefix][field] = list(msgs)
                else:
                    target[prefix] = {
                        field: list(msgs) for field, msgs in field_errors.items()
                    }
        else:
            for field, messages in (result.get(key) or {}).items():
                if field in target:
                    target[field].extend(messages)
                else:
                    target[field] = list(messages)

    def _build_fail_payload(
        self, doc_instance: Any, errors: dict, doc_type: str
    ) -> dict:
        """
        Minimal correctly-shaped payload for hard guard failures (e.g., locked document).
        Maintains structural parity with happy-path execution.
        """
        snapshot = SimpleNamespace(
            errors=errors,
            row_errors={},
            is_valid=False,
            rows_changed=False,
            totals={},
            header_changed=False,
            header_changes={},
        )
        return {
            "doc_instance": doc_instance,
            "doc_type": doc_type,
            "snapshot": snapshot,
            "ui_plan": {"swap": [], "triggers": ["show-validation-toast"]},
            "diff": {},
            "header": {},
            "items": {},
            "location": {},
            "calculation": {},
            "validation": {"errors": errors, "row_errors": {}},
            "state": None,
            "forms": None,
            # FIX: added for structural parity with build_outgoing_context's
            # now-required header_form key — without this, templates that
            # expect context["header_form"] on every response would KeyError
            # specifically on the locked-document path.
            "header_form": None,
        }

    def _build_header_form(
        self, doc_instance: Any, header_form_class, request, errors: dict
    ):
        """
        Builds the header ModelForm, binding it to submitted POST data when
        available so a validation error shows what the user actually typed
        rather than reverting to the last-saved instance values, then injects
        any service-layer errors on top of the form's own field errors.
        """
        # FIX: guard against an unregistered doc_type (header_form_class is
        # None) the same way _build_forms already guards formset_class.
        if not header_form_class:
            return None

        # FIX: request is Optional — never assume it's present or that it
        # carries .company.
        company = getattr(request, "company", None) if request else None

        # FIX: bind to POST data when this was a POST request, so the header
        # form reflects what was actually submitted (matching _build_forms'
        # row-rebinding behavior) instead of always showing stale DB values.
        # is_valid() triggers full_clean(), surfacing the form's own
        # field-level errors (e.g. required-field checks) before we layer
        # the service-layer errors on top.
        if request is not None and request.method == "POST" and errors:
            form = header_form_class(request.POST, instance=doc_instance, company=company)
            form.is_valid()
        else:
            form = header_form_class(instance=doc_instance, company=company)

        if not errors:
            return form

        if form._errors is None:
            form._errors = ErrorDict()

        for field, messages in errors.items():
            if not isinstance(messages, list):
                messages = [messages]

            if field in form._errors:
                form._errors[field].extend(messages)
            else:
                form._errors[field] = ErrorList(messages)

        return form

    def _build_forms(self, doc_instance: Any, formset_class, request, row_errors: dict):
        """Rebinds and injects service-layer errors into Django formsets dynamically."""
        if not formset_class:
            return None


        base_qs = doc_instance.lines.order_by("pk")

        forms = formset_class(
            instance=doc_instance,
            prefix="items",
            queryset=base_qs,
            form_kwargs={"doc": doc_instance},

        )

        if row_errors and request and request.method == "POST":
            row_prefix = request.POST.get("row_prefix")

            # Re-bind active single row if targeting individual line items
            if row_prefix:
                for form in forms:
                    if getattr(form, "prefix", None) == row_prefix:
                        form.data = request.POST
                        form.is_bound = True
                        form.full_clean()
                        break

            # Inject service-layer validation errors inline into form instances
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

    def _resolve_formset_class(self, doc_type: str) -> Optional[Any]:
        """
        Lazily resolves the default item-formset class for a given doc_type.
        Imports happen inside the branches to avoid circular imports between
        core/, accounting/, sales/, and purchases/.

        Callers can still override by passing formset_class explicitly into
        apply_state() — that always takes priority over this registry.
        """
        if doc_type in ["sales_invoice", "supplier_invoice", "entry"]:
            from accounting.forms.account_move_form import MoveLineFormSet
            return MoveLineFormSet

        if doc_type == "sales_order":
            from sales.forms.sales_order_form import SalesOrderLineFormSet
            return SalesOrderLineFormSet

        if doc_type == "purchase_order":
            from purchases.forms.purchase_order_form import PurchaseOrderLineFormSet
            return PurchaseOrderLineFormSet

        logger.warning("No formset registered for doc_type=%s", doc_type)
        return None

    def _resolve_header_form(self, doc_type: str):
        if doc_type in ["sales_invoice", "supplier_invoice", "entry"]:
            from accounting.forms.account_move_form import MoveForm
            return MoveForm

        if doc_type == "sales_order":
            from sales.forms.sales_order_form import SalesOrderForm
            return SalesOrderForm

        if doc_type == "purchase_order":
            from purchases.forms.purchase_order_form import PurchaseOrderForm
            return PurchaseOrderForm

        logger.warning("No form registered for doc_type=%s", doc_type)
        return None

    # =========================================================
    # MAIN PIPELINE
    # =========================================================

    @transaction.atomic
    def apply_state(
        self,
        doc_instance: Any,
        payload: dict,
        request: Optional[Any] = None,
        user: Optional[Any] = None,
        source: str = "htmx",
        formset_class: Optional[Any] = None,
        dropped_unsaved_rows: bool = False,
    ) -> dict:

        # =====================================================
        # 0. RESOLVE doc_type-SPECIFIC COLLABORATORS
        # =====================================================

        doc_type = payload.get("doc_type")



        if not doc_type:
            raise ValueError("payload must include 'doc_type'")

        self.state_service = self.state_service_registry[doc_type]  # KeyError if unrecognized
        formset_class = formset_class or self._resolve_formset_class(doc_type)
        header_form_class = self._resolve_header_form(doc_type)

        errors: dict = {}
        row_errors: dict = {}
        warnings: dict = {}
        row_warnings: dict = {}

        # =====================================================
        # 1. STATE GUARD (edit-lock only — not a transition check)
        # =====================================================
        if not self.state_service.is_editable(doc_instance):
            return self._build_fail_payload(
                doc_instance=doc_instance,
                errors={"document": ["This document is locked and cannot be edited."]},
                doc_type=doc_type,
            )

        # =====================================================
        # 2. PRE-MUTATION SNAPSHOT
        # =====================================================
        target_location = payload.get("header", {}).get("fulfillment_location") or getattr(
            doc_instance, "source_location_id", None
        )


        totals_before = self.calculation_service.recalculate(doc_instance)
        snapshot_before = DocumentSnapshot.capture(doc_instance, totals=totals_before)


        # =====================================================
        # 3. ORCHESTRATOR — Sync Header, Items, and Location
        # =====================================================
        sync_result = self.sync_orchestrator.sync_document(
            doc_instance=doc_instance,
            payload=payload,
            location=target_location,
        )



        header_result = sync_result.get("header") or {}
        items_result = sync_result.get("items") or {}
        location_result = sync_result.get("location") or {}





        if sync_result.get("conflicts"):
            logger.info("Payload alignment adjustments: %s", sync_result["conflicts"])

        self._collect(errors, header_result, key="errors")
        self._collect(row_errors, items_result, key="row_errors")

        logger.debug("After sync — errors: %s | row_errors: %s", errors, row_errors)

        # =====================================================
        # 4. CALCULATION
        # =====================================================
        calculation_result = self.calculation_service.recalculate(doc_instance)
        totals_after = calculation_result

        # =====================================================
        # 5. VALIDATION
        # =====================================================
        validation_result = self.validation_service.validate_document(
            doc_instance, doc_type=doc_type
        )

        self._collect(errors, validation_result, key="errors")
        self._collect(row_errors, validation_result, key="row_errors")
        self._collect(warnings, validation_result, key="warnings")
        self._collect(row_warnings,validation_result, key="row_warnings")

        # =====================================================
        # 6. BUILD POST-OPERATION SNAPSHOT
        # =====================================================
        if location_result.get("deleted"):
            row_errors["location_deleted_items"] = location_result["deleted"]

        snapshot_after = DocumentSnapshot(document=doc_instance, totals=totals_after)
        snapshot_after.state_before = snapshot_before.state_before
        snapshot_after.state_after = DocumentSnapshot._read_state(doc_instance)
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
        snapshot_after.row_warnings = row_warnings
        snapshot_after.warnings = warnings

        diff = DocumentSnapshot.diff(snapshot_before, snapshot_after)
        snapshot_after.amounts_changed = diff["amounts_changed"]
        snapshot_after.state_changed = diff["state_changed"]

        logger.debug("Snapshot diff: %s", diff)

        # =====================================================
        # 7. UI PLAN GENERATION
        # =====================================================
        logger.debug(
            "rows_changed=%s row_changes=%s",
            snapshot_after.rows_changed,
            snapshot_after.row_changes,
        )


        meta = payload.get("meta", {})
        ui_plan = self.ui_service.build_ui_plan(
            snapshot=snapshot_after,
            dropped_unsaved_rows=dropped_unsaved_rows,
            row_mode=meta.get("row_mode", False),
        )
        logger.info(f"ui plan: {ui_plan}")

        # =====================================================
        # 8. BUILD FORMS (Must execute before transaction rollback)
        # =====================================================
        forms = self._build_forms(doc_instance, formset_class, request, row_errors)
        header_form = self._build_header_form(doc_instance, header_form_class, request, errors)

        # =====================================================
        # 9. TRANSACTION COMMIT / ROLLBACK
        # =====================================================
        logger.info("Pre-save — errors: %s | row_errors: %s", errors, row_errors)

        hard_row_errors = {
            k: v for k, v in row_errors.items() if k != "location_deleted_items"
        }

        if not errors and not hard_row_errors:
            try:
                doc_instance.save()
                logger.info(
                    "Document type=%s pk=%s saved successfully.",
                    doc_type,
                    doc_instance.pk,
                )

                doc_instance.refresh_from_db()
                snapshot_after.totals = self.calculation_service.recalculate(doc_instance)

                forms = self._build_forms(
                    doc_instance, formset_class, request, row_errors
                )
                header_form = self._build_header_form(
                    doc_instance, header_form_class, request, errors
                )

            except Exception as exc:
                logger.exception("Document save failed: %s", exc)
                errors["save"] = [str(exc)]
                snapshot_after.errors = errors
                snapshot_after.is_valid = False
                transaction.set_rollback(True)
        else:
            transaction.set_rollback(True)
            logger.warning(
                "Transaction rolled back — errors=%s | row_errors=%s",
                errors,
                row_errors,
            )



        return build_outgoing_context(
            doc_instance=doc_instance,
            doc_type=doc_type,
            snapshot=snapshot_after,
            ui_plan=ui_plan,
            diff=diff,
            header=header_result,
            items=items_result,
            location=location_result,
            calculation=calculation_result,
            validation=validation_result,
            state=None,
            forms=forms,
            header_form=header_form,
        )