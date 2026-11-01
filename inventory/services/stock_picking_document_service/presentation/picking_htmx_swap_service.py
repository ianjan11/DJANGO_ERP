import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from django.forms import BaseFormSet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

logger = logging.getLogger("inventory.stock_picking")

# adjust to your template path
RESPONSE_TEMPLATE = "inventory/pickings/partials/picking_update_response.html"

SWAP_KEYS = ("header", "items", "item-row", "totals")


class UIResponseService:
    """
    Renders HTMX partial responses and builds HX-Trigger headers
    for the StockPicking screen, based on the UI plan and snapshot.
    """

    @classmethod
    def render(cls, request: HttpRequest, payload: Dict[str, Any]) -> HttpResponse:
        # 1. UI PLAN
        ui_plan = payload.get("ui_plan") or {}
        swap_targets: List[str] = ui_plan.get("swap") or []
        triggers: List[Union[str, Dict[str, Any]]] = ui_plan.get("triggers") or []

        # 2. SNAPSHOT / VALIDATION METADATA
        snapshot = payload.get("snapshot")
        errors = getattr(snapshot, "errors", {}) or {}
        row_errors = getattr(snapshot, "row_errors", {}) or {}
        warnings = getattr(snapshot, "warnings", {}) or {}
        row_warnings = getattr(snapshot, "row_warnings", {}) or {}
        is_valid = getattr(snapshot, "is_valid", True)

        def trigger_header() -> str:
            return cls._build_trigger_header(
                triggers, is_valid, errors, row_errors, warnings, row_warnings
            )

        # Nothing to swap. Triggers alone (e.g. the locked-picking toast) are
        # still delivered: HTMX reads HX-Trigger even on a 204.
        if not swap_targets:
            response = HttpResponse(status=204)
            if triggers:
                response["HX-Trigger"] = trigger_header()
            return response

        # 3. FORMS & ACTIVE ROW
        formset = payload.get("forms")
        row_prefix = request.POST.get("row_prefix") or request.GET.get("row_prefix")
        active_form = cls._resolve_active_form(
            formset=formset,
            request=request,
            row_prefix=row_prefix,
            items_result=payload.get("items") or {},
        )

        picking = payload.get("picking")
        print(picking)

        # 4. CONTEXT
        context: Dict[str, Any] = {
            "picking": picking,
            "doc_instance": picking,
            "snapshot": snapshot,
            "diff": payload.get("diff"),

            "header_form": payload.get("header_form"),
            "formset": formset,
            "form": active_form,

            "header_data": payload.get("header"),
            "items_data": payload.get("items"),

            "header_errors": errors,
            "errors": errors,
            "row_errors": row_errors,
            "warnings": warnings,
            "row_warnings": row_warnings,
            "is_valid": is_valid,

            "swap_targets": swap_targets,
            "swap": {k.replace("-", "_"): (k in swap_targets) for k in SWAP_KEYS},
        }

        # 5. RENDER
        response = render(request, RESPONSE_TEMPLATE, context, status=200 if is_valid else 400)

        # 6. HX-TRIGGER
        if triggers:
            response["HX-Trigger"] = trigger_header()

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
    # HX-TRIGGER HEADER
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
    ) -> str:
        htmx_triggers: Dict[str, Any] = {}

        for trigger in triggers:
            name: Optional[str] = None
            level: Optional[str] = None

            if isinstance(trigger, dict):
                name, level = trigger.get("event"), trigger.get("level")
            elif isinstance(trigger, str):
                name, _, level = trigger.partition(":")
                level = level or None

            if not name:
                continue

            if name in ("showNotification", "show-validation-toast"):
                if level == "error" or not is_valid:
                    count = _count_nested_messages(errors) + _count_nested_messages(row_errors)
                    htmx_triggers[name] = {"message": _validation_message(count), "level": "error"}
                elif level == "warning" or warnings or row_warnings:
                    htmx_triggers[name] = {
                        "message": _warning_message(warnings, row_warnings),
                        "level": "warning",
                    }
                elif level == "success":
                    htmx_triggers[name] = {"message": "Transfer saved successfully.", "level": "success"}
            else:
                # Plain HTMX event, e.g. "refresh-totals"
                htmx_triggers[name] = True

        return json.dumps(htmx_triggers)


# =============================================================
# NOTIFICATION HELPERS
# =============================================================

def _count_nested_messages(data: Any) -> int:
    """Recursively count messages in nested dicts/lists."""
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


def _row_label(prefix: Any) -> str:
    """'items-0' -> 'Row 1' (1-based, as the user sees it); anything else as-is."""
    match = re.fullmatch(r"items-(\d+)", str(prefix))
    return f"Row {int(match.group(1)) + 1}" if match else f"Row {prefix}"


def _format_field_warnings(msgs: Any) -> str:
    if isinstance(msgs, dict):
        parts = []
        for field, errs in msgs.items():
            label = "" if field == "__all__" else f"{field.replace('_', ' ').title()}: "
            detail = "; ".join(map(str, errs)) if isinstance(errs, (list, tuple)) else str(errs)
            parts.append(f"{label}{detail}")
        return ", ".join(parts)
    if isinstance(msgs, (list, tuple)):
        return "; ".join(map(str, msgs))
    return str(msgs)


def _warning_message(warnings: Dict[str, Any], row_warnings: Dict[str, Any]) -> str:
    """Header-level and row-level warnings as a readable toast body."""
    total = _count_nested_messages(warnings) + _count_nested_messages(row_warnings)
    if total == 0:
        return ""

    label = "warning needs" if total == 1 else "warnings need"
    lines = [f"{total} {label} attention:"]

    for field, msgs in (warnings or {}).items():
        lines.append(f"• {_format_field_warnings(msgs)}")

    for prefix, msgs in (row_warnings or {}).items():
        lines.append(f"• {_row_label(prefix)}: {_format_field_warnings(msgs)}")

    return "\n".join(lines)