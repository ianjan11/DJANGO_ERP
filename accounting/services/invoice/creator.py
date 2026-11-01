from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from accounting.models import AccountMove, Journal
from core.models import SequenceRegistry
from core.services.partner_defaults import DocumentType, resolve_document_defaults



DOCUMENT_TYPE_BY_INVOICE_TYPE = {
    "out_invoice": DocumentType.OUT_INVOICE,  # Customer Invoice
    "in_invoice": DocumentType.IN_INVOICE,  # Vendor Bill
    "out_refund": DocumentType.OUT_REFUND,  # Customer Credit Note
    "in_refund": DocumentType.IN_REFUND,  # Vendor Credit Note
}

# Map AccountMove.move_type -> Journal.type
JOURNAL_TYPE_BY_INVOICE_TYPE = {
    "out_invoice": "SALE",
    "in_invoice": "PURCHASE",
    "out_refund": "SALE",
    "in_refund": "PURCHASE",
}

def resolve_journal_for_invoice_type(company, invoice_type):
    """
    Resolves the appropriate Journal for a given invoice type within a company.

    1. Look up required string type ('SALE' or 'PURCHASE').
    2. Retrieve the active journal matching that company and type.
    """
    expected_journal_type = JOURNAL_TYPE_BY_INVOICE_TYPE.get(invoice_type)

    if not expected_journal_type:
        raise ValueError(f"Unsupported or unknown invoice_type: '{invoice_type}'")

    journal = (
        Journal.objects.filter(
            company=company,
            type=expected_journal_type,
            # Add is_active=True here if your model supports soft deletion/archiving
        )
        .order_by("id")
        .first()
    )

    if not journal:
        raise ValidationError(
            f"No active '{expected_journal_type}' journal found for company '{company.name}'. "
            f"Please create/configure a '{expected_journal_type}' Journal before creating {invoice_type} documents."
        )

    return journal



def _extract_val(result_or_obj):
    """Safely extracts .value if it's a wrapper object, else returns the object itself."""
    if result_or_obj is None:
        return None
    return result_or_obj.value if hasattr(result_or_obj, 'value') else result_or_obj

@transaction.atomic
def create_invoice(request, invoice_type, partner=None):
    """
    Creates a draft AccountMove. Resolves currency, location, and payment terms
    via partner defaults, and resolves the journal strictly by the invoice_type
    and company context.
    """
    company = getattr(request, "company", None)
    if not company:
        raise ValidationError("An active company is required.")

    document_type = DOCUMENT_TYPE_BY_INVOICE_TYPE.get(invoice_type)
    if not document_type:
        raise ValidationError(f"Invalid invoice type: {invoice_type}")

    # 1. Resolve journal based strictly on invoice_type and company
    journal = resolve_journal_for_invoice_type(company, invoice_type)
    if not journal:
        raise ValidationError(f"No valid journal found for invoice type '{invoice_type}'.")

    # 2. Resolve partner & document defaults
    defaults = resolve_document_defaults(request.user, document_type, partner=partner) or {}

    currency = _extract_val(defaults.get("currency")) or company.currency
    fulfillment_location = _extract_val(defaults.get("location"))
    payment_term = _extract_val(defaults.get("payment_term"))

    # 3. Instantiate and save the draft move
    invoice = AccountMove.objects.create(
        state=AccountMove.State.DRAFT,
        created_by=request.user,
        partner=partner,
        currency=currency,
        journal=journal,
        fulfillment_location=fulfillment_location,
        payment_term=payment_term,
        company=company,
        move_type=invoice_type,
        issue_date=timezone.now().date(),
    )

    return invoice

def refresh_invoice_defaults(invoice, user, partner):
    """
    Updates partner-dependent defaults (e.g., payment terms or currency preferences)
    when a partner is assigned or changed on a draft invoice.

    NOTE: Journal remains unchanged as it is tied to invoice_type/company, not partner.
    """
    document_type = DOCUMENT_TYPE_BY_INVOICE_TYPE[invoice.move_type]

    defaults = resolve_document_defaults(user, document_type, partner=partner)

    invoice.partner = partner
    if defaults.get("currency"):
        invoice.currency = defaults["currency"].value if hasattr(defaults["currency"], 'value') else defaults[
            "currency"]
    if defaults.get("payment_term"):
        invoice.payment_term = defaults["payment_term"].value if hasattr(defaults["payment_term"], 'value') else \
        defaults["payment_term"]

    invoice.save(update_fields=["partner", "currency", "payment_term"])

    return invoice, defaults

def generate_invoice_number(company):
    seq = SequenceRegistry.get_next_sequence('ACCOUNT_MOVE', company)
    date_str = timezone.now().date().strftime("%Y%m%d")
    reference = f"INV-{date_str}-{seq:05d}"
    return reference