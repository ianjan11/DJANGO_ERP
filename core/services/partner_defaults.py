from collections import namedtuple

Resolved = namedtuple("Resolved", ["value", "source"])
# source is one of: "document", "partner", "profile", None (unresolved)


class DocumentType:
    SALE_ORDER = "SALE_ORDER"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    OUT_INVOICE = "OUT_INVOICE"   # Customer Invoice
    IN_INVOICE = "IN_INVOICE"     # Vendor Bill
    IN_REFUND = "IN_REFUND"
    OUT_REFUND = "OUT_REFUND"


# Direction drives which fields apply: OUT = Customer Facing, IN = Vendor Facing
DIRECTION_BY_DOCUMENT_TYPE = {
    DocumentType.SALE_ORDER: "OUT",
    DocumentType.OUT_INVOICE: "OUT",
    DocumentType.PURCHASE_ORDER: "IN",
    DocumentType.IN_INVOICE: "IN",
    DocumentType.IN_REFUND: "IN",
    DocumentType.OUT_REFUND: "OUT",
}

# Mapping of attributes per direction
FIELD_SPEC = {
    "OUT": {
        "location": {
            "document_attr": "fulfillment_location",
            "partner_attr": "preferred_destination_location",
            "profile_attr": "default_location",
        },
        "currency": {
            "document_attr": "currency",
            "partner_attr": None,
            "profile_attr": "default_currency",
        },
        "payment_term": {
            "document_attr": "payment_term",
            "partner_attr": "payment_term",
            "profile_attr": "default_payment_term",
        },
    },
    "IN": {
        "location": {
            "document_attr": "fulfillment_location",
            # On IN documents (POs), stock is received into internal destination location
            "partner_attr": "preferred_destination_location",
            "profile_attr": "default_location",
        },
        "currency": {
            "document_attr": "currency",
            "partner_attr": None,
            "profile_attr": "default_currency",
        },
        "payment_term": {
            "document_attr": "payment_term",
            "partner_attr": "supplier_payment_term",
            "profile_attr": "default_payment_term",
        },
    },
}

PROFILE_ATTR = "profile"


class PartnerDirectionMismatch(ValueError):
    """Raised when a partner isn't eligible to act in the document's direction."""


def resolve_document_defaults(user, document_type, partner=None, source_document=None):
    """
    Returns a dict of {field: Resolved(value, source)} for a document.

    Priority (highest -> lowest):
      1. Source document values   (source="document") — if source has items
      2. Partner preference       (source="partner")  — resolved per direction
      3. User's profile default   (source="profile")  — user.profile
      4. Unresolved               (source=None)       — field left blank
    """
    if document_type not in DIRECTION_BY_DOCUMENT_TYPE:
        raise ValueError(f"Unknown document_type: {document_type}")

    direction = DIRECTION_BY_DOCUMENT_TYPE[document_type]
    spec = FIELD_SPEC[direction]

    if partner is not None:
        _assert_partner_direction(partner, direction)

    profile = getattr(user, PROFILE_ATTR, None)

    # 1. Source document values take precedence if items exist
    if source_document is not None and getattr(source_document, "has_items", lambda: False)():
        return {
            field: Resolved(getattr(source_document, cfg["document_attr"], None), "document")
            for field, cfg in spec.items()
        }

    # 2 & 3. Resolve through Partner or Profile
    result = {}
    for field, cfg in spec.items():
        partner_val = (
            getattr(partner, cfg["partner_attr"], None)
            if partner is not None and cfg["partner_attr"]
            else None
        )
        profile_val = getattr(profile, cfg["profile_attr"], None) if profile else None
        result[field] = _resolve_value(partner_val, profile_val)

    return result


def _resolve_value(partner_val, profile_val):
    if partner_val is not None:
        return Resolved(partner_val, "partner")
    if profile_val is not None:
        return Resolved(profile_val, "profile")
    return Resolved(None, None)


def _assert_partner_direction(partner, direction):
    if direction == "OUT" and not getattr(partner, "is_customer", True):
        raise PartnerDirectionMismatch(
            f"{partner} is not marked as a customer; cannot be used on an OUT document."
        )
    if direction == "IN" and not getattr(partner, "is_supplier", True):
        raise PartnerDirectionMismatch(
            f"{partner} is not marked as a vendor; cannot be used on an IN document."
        )