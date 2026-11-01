from decimal import Decimal
from typing import Tuple

from core.models import Partner
from core.services.document_service.field_normalize_service import FieldNormalizerService
from inventory.models import StockLocation, StockPickingType

normalizer = FieldNormalizerService()

PICKING_DOCUMENT_CONFIG = {
    "picking": {
        "doc_label": "Stock Transfer",
        "party_label": "Partner",
    },
}


def build_payload(post, doc_type: str = "picking") -> Tuple[dict, bool]:
    config = PICKING_DOCUMENT_CONFIG.get(doc_type, PICKING_DOCUMENT_CONFIG["picking"])

    # =========================================================
    # HEADER
    # =========================================================
    header = {
        "partner": post.get("partner"),
        "origin": post.get("origin"),
        "source_location": post.get("source_location"),
        "dest_location": post.get("dest_location"),
        "scheduled_date": post.get("scheduled_date"),
        "picking_type": post.get("picking_type"),
        "status": post.get("status"),
    }

    # Filter out keys not supplied in post
    header = {k: v for k, v in header.items() if k in post}

    header_mapping = {
        "partner": Partner,
        "source_location": StockLocation,
        "dest_location": StockLocation,
        "picking_type": StockPickingType,
        "scheduled_date": "datetime",
        "origin": str,
        "status": str,
    }

    updatable_fields = {k: v for k, v in header_mapping.items() if k in header}

    # =========================================================
    # FORMSET META
    # =========================================================
    row_prefix = post.get("row_prefix")
    total_forms = int(post.get("items-TOTAL_FORMS", 0) or 0)
    all_prefixes = [f"items-{i}" for i in range(total_forms)]

    active_prefix = row_prefix if row_prefix in all_prefixes else None

    # =========================================================
    # ROWS
    # =========================================================
    rows = []
    dropped_unsaved_rows = False

    for prefix in all_prefixes:
        try:
            index = int(prefix.split("-")[1])
        except (IndexError, ValueError):
            index = 0

        row = {
            "id": normalizer.to_int(post.get(f"{prefix}-id")),
            "product_id": normalizer.to_int(post.get(f"{prefix}-product")),
            "quantity": normalizer.to_decimal(post.get(f"{prefix}-quantity")),
            "product_uom_id": normalizer.to_str(post.get(f"{prefix}-product_uom")),
            "source_location": normalizer.to_int(post.get(f"{prefix}-source_location")),
            "dest_location": normalizer.to_int(post.get(f"{prefix}-dest_location")),
            "delete": post.get(f"{prefix}-DELETE") == "on",
            "index": index,
            "prefix": prefix,
            "is_active": prefix == active_prefix,
        }

        is_active_row = prefix == active_prefix

        # Rule 1 — unsaved + delete: drop always, even if active.
        if not row["id"] and row["delete"]:
            dropped_unsaved_rows = True
            if is_active_row:
                active_prefix = None
            continue

        # Rule 2 — active row: always keep, even if empty.
        if is_active_row:
            rows.append(row)
            continue

        # Rule 3 — empty unsaved non-active rows: drop.
        has_user_input = any([
            row["product_id"],
            row["quantity"] is not None,
            row.get("product_uom_id"),
        ])

        if not row["id"] and not has_user_input:
            dropped_unsaved_rows = True
            continue

        # Rule 4 — keep everything else
        rows.append(row)

    # =========================================================
    # PAYLOAD — matches DocumentService apply_state()'s expected shape
    # =========================================================
    payload = {
        "doc_type": doc_type,
        "header": header,
        "items": rows,
        "meta": {
            "source": "htmx",
            "row_prefix": row_prefix,
            "active_prefix": active_prefix,
            "row_mode": bool(active_prefix),
            "total_forms": total_forms,
        },
        "updatable_fields": updatable_fields,
        "dropped_unsaved_rows": dropped_unsaved_rows,
    }

    return payload, dropped_unsaved_rows


def build_outgoing_context(
    picking,
    snapshot,
    ui_plan,
    diff,
    header,
    items,
    validation,
    forms,
    header_form,
    doc_type: str = "picking",
) -> dict:
    config = PICKING_DOCUMENT_CONFIG.get(doc_type, PICKING_DOCUMENT_CONFIG["picking"])

    return {
        "picking": picking,
        "snapshot": snapshot,
        "ui_plan": ui_plan,
        "diff": diff,
        "header": header,
        "items": items,
        "validation": validation,
        "forms": forms,
        "header_form": header_form,
    }