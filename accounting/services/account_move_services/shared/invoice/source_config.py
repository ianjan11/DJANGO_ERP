from django.core.exceptions import ValidationError

SOURCE_CONFIG = {
    "out_invoice": {
        "journal_type": "SALE",
        "partner_account": "RECEIVABLE",
        "company_account": "default_receivable",
        "line_side": "CREDIT",
    },

    "out_refund": {
        "journal_type": "CUSTOMER_CREDIT",
        "partner_account": "RECEIVABLE",
        "company_account": "default_receivable",
        "line_side": "DEBIT",
    },

    "in_invoice": {
        "journal_type": "PURCHASE",
        "partner_account": "PAYABLE",
        "company_account": "default_payable",
        "line_side": "DEBIT",
    },

    "in_refund": {
        "journal_type": "VENDOR_CREDIT",
        "partner_account": "PAYABLE",
        "company_account": "default_payable",
        "line_side": "CREDIT",
    },
}


def get_config(invoice_type):
    config = SOURCE_CONFIG.get(invoice_type)

    if not config:
        raise ValidationError(
            f"Unsupported invoice type: {invoice_type}"
        )
    return config

