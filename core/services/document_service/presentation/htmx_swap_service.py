import json
import logging
from typing import Any, Dict, List, Optional, Union
from django.forms import BaseFormSet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

logger = logging.getLogger("sales.invoice")


class UIResponseService:
    """
    Renders HTMX partial responses and builds HX-Trigger headers
    based on UI execution plans and snapshot diffs.
    """

    INVOICE_DOC_TYPES = {
        "sales_invoice", "out_invoice", "supplier_invoice",
        "in_invoice", "move", "out_refund", "in_refund"
    }
    PURCHASE_DOC_TYPES = {"purchase_order"}
    SALES_ORDER_DOC_TYPES = {"sales_order", "quotation"}
    ENTRY_DOC_TYPES = {"entry"}




    @classmethod
    def render(
        cls,
        request: HttpRequest,
        payload: Dict[str, Any],
    ) -> HttpResponse:
        # =====================================================
        # 1. UI PLAN & SWAP TARGETS
        # =====================================================
        ui_plan = payload.get("ui_plan") or {"swap": [], "triggers": []}
        swap_targets: List[str] = ui_plan.get("swap") or []

        if not swap_targets:
            return HttpResponse(status=204)


        triggers: List[Union[str, Dict[str, Any]]] = ui_plan.get("triggers") or []


        # Return 204 No Content if HTMX has nothing to swap or trigger
        if not swap_targets and not triggers:
            return HttpResponse(status=204)

        # =====================================================
        # 2. SNAPSHOT & VALIDATION METADATA
        # =====================================================
        snapshot = payload.get("snapshot")

        errors = getattr(snapshot, "errors", {}) if snapshot else {}
        row_errors = getattr(snapshot, "row_errors", {}) if snapshot else {}
        warnings = getattr(snapshot, "warnings", {}) if snapshot else {}
        row_warnings = getattr(snapshot, "row_warnings", {}) if snapshot else {}
        is_valid = getattr(snapshot, "is_valid", True) if snapshot else True


        # =====================================================
        # 3. FORMS & ACTIVE ROW RESOLUTION
        # =====================================================
        header_form = payload.get("header_form")
        formset = payload.get("forms")


        row_prefix = (
            request.POST.get("row_prefix")
            or request.GET.get("row_prefix")
        )

        active_form = cls._resolve_active_form(
            formset=formset,
            request=request,
            row_prefix=row_prefix,
            items_result=payload.get("items") or {},
        )



        doc_instance = payload.get("doc_instance") or payload.get("move")
        doc_type = payload.get("doc_type", "move")

        # =====================================================
        # 4. CONTEXT ASSEMBLY
        # =====================================================
        SWAP_KEYS = ("header", "items", "item-row", "totals")

        context: Dict[str, Any] = {
            # Core Document
            "doc_instance": doc_instance,
            "doc_type": doc_type,
            "snapshot": snapshot,
            "diff": payload.get("diff"),

            # Formsets & Forms
            "header_form": header_form,
            "formset": formset,
            "form": active_form,

            # Service Data Outputs
            "header_data": payload.get("header"),
            "items_data": payload.get("items"),
            "calculation": payload.get("calculation"),
            "location": payload.get("location"),

            # Validation & Errors
            "header_errors": errors,
            "errors": errors,
            "row_errors": row_errors,
            "warnings": warnings,
            "row_warnings": row_warnings,
            "is_valid": is_valid,

            # UI Control
            "swap_targets": swap_targets,
            "swap": {k.replace("-", "_"): (k in swap_targets) for k in SWAP_KEYS},
        }



        # Context aliases for template backward compatibility
        if doc_type in cls.INVOICE_DOC_TYPES:
            context["invoice"] = doc_instance
            context["move"] = doc_instance
        elif doc_type in cls.PURCHASE_DOC_TYPES:
            context["purchase"] = doc_instance
        elif doc_type in cls.SALES_ORDER_DOC_TYPES:
            context["order"] = doc_instance
        elif doc_type in cls.ENTRY_DOC_TYPES:
            context["move"] = doc_instance

        # =====================================================
        # 5. TEMPLATE RESOLUTION & RENDER
        # =====================================================
        template_name = cls._resolve_template(doc_type)

        response = render(
            request,
            template_name,
            context,
            status=200 if is_valid else 400,
        )

        # =====================================================
        # 6. HTMX TRIGGER HEADER
        # =====================================================
        if triggers:
            response["HX-Trigger"] = cls._build_trigger_header(
                triggers=triggers,
                is_valid=is_valid,
                errors=errors,
                row_errors=row_errors,
                warnings=warnings,
                row_warnings=row_warnings,
                doc_type=doc_type,
            )

        return response

    # =========================================================
    # ACTIVE FORM RESOLUTION
    # =========================================================

    @staticmethod
    def _resolve_active_form(
        formset: Any,
        request: HttpRequest,
        row_prefix: Optional[str],
        items_result: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Resolves the exact form corresponding to the submitted active row.
        """
        if not formset or not row_prefix:
            return None

        # Extract underlying form list safely from FormSet or dict wrapper
        forms_list = []
        if isinstance(formset, BaseFormSet):
            forms_list = formset.forms
        elif isinstance(formset, dict):
            forms_list = formset.get("forms") or []
        elif isinstance(formset, (list, tuple)):
            forms_list = formset

        # 1. Check existing row ID in POST data
        item_id = request.POST.get(f"{row_prefix}-id")
        if item_id:
            form = next(
                (
                    f for f in forms_list
                    if getattr(f, "instance", None)
                    and str(f.instance.pk) == str(item_id)
                ),
                None,
            )
            if form:
                return form

        # 2. Check newly created item ID
        created_ids = items_result.get("created") or []
        if not item_id and len(created_ids) == 1:
            new_id = created_ids[0]
            form = next(
                (
                    f for f in forms_list
                    if getattr(f, "instance", None)
                    and str(f.instance.pk) == str(new_id)
                ),
                None,
            )
            if form:
                return form

        # 3. Fallback to prefix match
        return next(
            (f for f in forms_list if getattr(f, "prefix", None) == row_prefix),
            None,
        )

    # =========================================================
    # TEMPLATE RESOLUTION
    # =========================================================

    RESPONSE_TEMPLATES = {
        "invoice": "accounting/move_templates/partials/move_update_response.html",
        "sales_order": "sales/partials/order_update_response.html",
        "purchase": "purchases/partials/purchase_update_response.html",
        "entry": "accounting/journals/partials/journal_update_response.html",
    }

    @classmethod
    def _resolve_template(cls, doc_type: str) -> str:
        """Return the single combined-response template for a document type."""
        if doc_type in cls.INVOICE_DOC_TYPES:
            return cls.RESPONSE_TEMPLATES["invoice"]
        if doc_type in cls.SALES_ORDER_DOC_TYPES:
            return cls.RESPONSE_TEMPLATES["sales_order"]
        if doc_type in cls.PURCHASE_DOC_TYPES:
            return cls.RESPONSE_TEMPLATES["purchase"]
        if doc_type in cls.ENTRY_DOC_TYPES:
            return cls.RESPONSE_TEMPLATES["entry"]
        raise ValueError(f"Unknown doc_type: {doc_type}")


    # =========================================================
    # HTMX TRIGGER HEADER BUILDER
    # =========================================================

    @classmethod
    def _build_trigger_header(
        cls,
        triggers: List[Union[str, Dict[str, Any]]],
        is_valid: bool,
        errors: dict,
        row_errors: dict,
        warnings: dict,
        row_warnings: dict,
        doc_type: str,
    ) -> str:
        """Build the HX-Trigger JSON header enriched with contextual payloads."""
        htmx_triggers: Dict[str, Any] = {}

        for trigger in triggers:
            trigger_name: Optional[str] = None
            level: Optional[str] = None

            if isinstance(trigger, dict):
                trigger_name = trigger.get("event")
                level = trigger.get("level")
            elif isinstance(trigger, str):
                if ":" in trigger:
                    trigger_name, level = trigger.split(":", 1)
                else:
                    trigger_name = trigger

            if not trigger_name:
                continue

            # Notification Trigger
            if trigger_name in ("showNotification", "show-validation-toast"):
                if level == "error" or not is_valid:
                    error_count = _count_nested_messages(errors) + _count_nested_messages(row_errors)
                    htmx_triggers[trigger_name] = {
                        "message": _validation_message(error_count),
                        "level": "error",
                    }
                elif level == "warning" or warnings or row_warnings:
                    warning_count = _count_nested_messages(warnings) + _count_nested_messages(row_warnings)
                    htmx_triggers[trigger_name] = {
                        "message": _warning_message(warning_count, warnings),
                        "level": "warning",
                    }
                elif level == "success":
                    doc_label = "Journal entry" if doc_type in cls.INVOICE_DOC_TYPES else "Document"
                    htmx_triggers[trigger_name] = {
                        "message": f"{doc_label} saved successfully.",
                        "level": "success",
                    }

            # Standard HTMX Event (e.g., "refresh-totals", "refresh-header")
            else:
                htmx_triggers[trigger_name] = True

        return json.dumps(htmx_triggers)


# =============================================================
# NOTIFICATION HELPER FUNCTIONS
# =============================================================

def _count_nested_messages(data: Any) -> int:
    """Recursively counts items/messages in dicts or lists safely."""
    if not data:
        return 0
    if isinstance(data, (list, tuple, set)):
        return sum(_count_nested_messages(item) for item in data)
    if isinstance(data, dict):
        return sum(_count_nested_messages(v) for v in data.values())
    return 1


def _validation_message(error_count: int) -> str:
    if error_count == 0:
        return "Please fix the highlighted issues."
    if error_count == 1:
        return "1 field needs attention. Please fix the highlighted issue."
    return f"{error_count} fields need attention. Please fix the highlighted issues."


def _warning_message(warning_count: int, row_warnings: Dict[str, Any]) -> str:
    """
    Formats warnings into a structured, readable string ideal for Toasts or Banners.
    """
    if not row_warnings or warning_count == 0:
        return ""

    label = "warning needs" if warning_count == 1 else "warnings need"
    lines = [f"{warning_count} {label} attention:"]

    for row_prefix, msgs in row_warnings.items():
        # Handle dicts like {"quantity": ["Insufficient stock"]}
        if isinstance(msgs, dict):
            parts = []
            for field, errs in msgs.items():
                field_label = "" if field == "__all__" else f"{field.replace('_', ' ').title()}: "
                detail = "; ".join(str(e) for e in errs) if isinstance(errs, (list, tuple)) else str(errs)
                parts.append(f"{field_label}{detail}")
            lines.append(f"• Row {row_prefix}: {', '.join(parts)}")

        # Handle list of string warnings
        elif isinstance(msgs, (list, tuple)):
            lines.append(f"• Row {row_prefix}: {'; '.join(str(m) for m in msgs)}")

        # Handle plain string
        else:
            lines.append(f"• Row {row_prefix}: {msgs}")

    return "\n".join(lines)

