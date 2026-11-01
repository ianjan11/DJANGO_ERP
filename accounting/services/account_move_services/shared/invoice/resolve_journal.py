from django.core.exceptions import ValidationError

from accounting.models import Journal
from accounting.services.account_move_services.shared.invoice.source_config import get_config



def resolve_journal(invoice, invoice_type):
    company = invoice.company

    if invoice_type in ("out_invoice", "out_refund"):
        journal_type = "SALE"

    elif invoice_type in ("in_invoice", "in_refund"):
        journal_type = "PURCHASE"

    else:
        raise ValidationError(
            f"Unsupported invoice type: {invoice_type}"
        )

    journal = (
        Journal.objects
        .filter(
            company=company,
            type=journal_type,
        )
        .first()
    )

    if journal is None:
        raise ValidationError(
            f"No active {journal_type} journal configured "
            f"for company '{company}'."
        )

    return journal