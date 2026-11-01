from decimal import Decimal
from locale import currency

from accounting.models import PaymentTerm, Account, Journal
from core.models import Partner
from core.models import Currency
from core.services.currency_exchange_service import currency_id
from core.services.document_service.field_normalize_service import FieldNormalizerService
from inventory.models import StockLocation, Warehouse

normalizer = FieldNormalizerService()

DOCUMENT_CONFIG = {
    "sales_invoice": {
        "doc_label":   "AccountMove",
        "party_label": "Customer",
    },

    "supplier_invoice": {
        "doc_label":   "AccountMove",
        "party_label": "Vendor",
    },

   "entry": {
        "doc_label":   "AccountMove",
        "party_label": "Entry",
        "extra_fields": {
            "journal_id": "journal",
        },
    },

    "sales_order": {
        "doc_label":   "Sales Order",
        "party_label": "Customer",
    },
    "purchase_order": {
        "doc_label":   "Purchase Order",
        "party_label": "Vendor",
        "extra_fields": {
            "expected_date": "expected_date",
        },
    },
}

def _infer_line_type(row):
    """
    A row is either a product line (has a product) or a plain journal
    line (manual debit/credit with a memo, no product). Ambiguous or
    fully-empty rows are left as None and resolved downstream —
    _create_item still defaults empty new rows to PRODUCT so an
    empty add-row doesn't need the user to pick a type up front.
    """
    if row["product_id"]:
        return "product"
    if row["debit"] is not None or row["credit"] is not None or row["memo"]:
        return "plain"
    return None

def build_payload(post, doc_type):
    config = DOCUMENT_CONFIG.get(doc_type)
    if config is None:
        raise ValueError(
            f"Unknown doc_type '{doc_type}'. Expected one of: {list(DOCUMENT_CONFIG)}"
        )

    # =========================================================
    # HEADER
    # =========================================================

    header = {
        "status": post.get("status"),
        "payment_term": post.get("payment_term"),
        "partner": post.get("partner"),
        "fulfillment_location": post.get("fulfillment_location"),
        "issue_date": post.get("issue_date"),
        "narration": post.get("narration"),
        "ref": post.get("ref"),
        "currency": post.get("currency"),
    }

    # Merge any remaining doc-type-specific fields (currently: PO's expected_date)
    header.update({
        header_key: post.get(post_key)
        for header_key, post_key in config.get("extra_fields", {}).items()
    })


    header_mapping = {
        "partner": Partner,
        "payment_term": PaymentTerm,
        "fulfillment_location": Warehouse,
        "currency": Currency,
        "issue_date": "date",
        "expected_date": "date",
        "status": str,
        "notes": str,
        "journal_id": Journal,
        "narration": str,
        "ref": str,

    }

    updatable_fields = {k: v for k, v in header_mapping.items() if k in header}


    # =========================================================
    # FORMSET META
    # =========================================================
    row_prefix   = post.get("row_prefix")
    total_forms  = int(post.get("items-TOTAL_FORMS", 0))
    all_prefixes = [f"items-{i}" for i in range(total_forms)]

    active_prefix = row_prefix if row_prefix in all_prefixes else None

    # =========================================================
    # ROWS
    # =========================================================
    rows                 = []
    dropped_unsaved_rows = False

    for prefix in all_prefixes:

        try:
            index = int(prefix.split("-")[1])
        except (IndexError, ValueError):
            index = 0

        row = {
            "id":               normalizer.to_int(post.get(f"{prefix}-id")),
            "product_id":       normalizer.to_int(post.get(f"{prefix}-product")),
            "description":      normalizer.to_str(post.get(f"{prefix}-description")),
            "quantity":         normalizer.to_decimal(post.get(f"{prefix}-quantity")),
            "price_unit":       normalizer.to_decimal(post.get(f"{prefix}-price_unit")),
            "discount_percent": normalizer.to_decimal(post.get(f"{prefix}-discount_percent")),
            "product_uom_id":   normalizer.to_str(post.get(f"{prefix}-product_uom")),
            "memo":             normalizer.to_str(post.get(f"{prefix}-memo")),
            "partner_id":       normalizer.to_int(post.get(f"{prefix}-partner")),
            "debit":            normalizer.to_decimal(post.get(f"{prefix}-debit")),
            "credit":           normalizer.to_decimal(post.get(f"{prefix}-credit")),
            "taxes":            post.getlist(f"{prefix}-taxes"),
            "delete":           post.get(f"{prefix}-DELETE") == "on",
            "index":            index,
            "prefix":           prefix,
            "is_active":        prefix == active_prefix,
            "taxes_touched": post.get(f"{prefix}-taxes_touched") == "1",

        }


        if doc_type in ("sales_invoice", "supplier_invoice", "entry",):
            row["account_id"] =  normalizer.to_int(post.get(f"{prefix}-account"))

        row["line_type"] = _infer_line_type(row)

        row["line_type"] = _infer_line_type(row)

        if row["line_type"] == "plain":
            row["product_id"] = None
            row["quantity"] = None
            row["discount_percent"] = Decimal("0.00")
            row["price_unit"] = Decimal("0.00")

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
            row["description"],
            row["quantity"]         is not None,
            row["memo"] is not None,
            row["debit"] is not None,
            row["credit"] is not None,
            row["price_unit"]       is not None,
            row["discount_percent"] not in (None, Decimal("0")),
            row["taxes"],
            row.get("account_id"),
            row.get("product_uom_id"),
            row.get("partner_id"),
        ])

        if not row["id"] and not has_user_input:
            dropped_unsaved_rows = True
            continue

        # Rule 4 — everything else: keep.
        rows.append(row)

    # =========================================================
    # PAYLOAD — matches apply_state()'s expected shape
    # =========================================================
    payload = {
        "doc_type": doc_type,
        "header":   header,
        "items":    rows,
        "meta": {
            "source":        "htmx",
            "row_prefix":    row_prefix,
            "active_prefix": active_prefix,
            "row_mode":      bool(active_prefix),
            "total_forms":   total_forms,
        },
        "updatable_fields": updatable_fields,
    }

    return payload, dropped_unsaved_rows


def build_outgoing_context(
    doc_instance,
    doc_type,
    snapshot,
    ui_plan,
    diff,
    header,
    items,
    location,
    calculation,
    validation,

    state,
    forms,
        header_form,
) -> dict:
    config = DOCUMENT_CONFIG.get(doc_type, {})

    return {
        "doc_instance": doc_instance,
        "doc_type":     doc_type,
        "doc_label":    config.get("doc_label", ""),
        "party_label":  config.get("party_label", ""),
        "snapshot":     snapshot,
        "ui_plan":      ui_plan,
        "diff":         diff,
        "header":       header,
        "items":        items,
        "location":     location,
        "calculation":  calculation,
        "validation":   validation,
        "state":        state,
        "forms":        forms,
        "header_form": header_form,
    }