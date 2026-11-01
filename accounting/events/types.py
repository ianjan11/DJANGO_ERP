class AccountingEventType:

    INVOICE_CREATED = "invoice.created"
    INVOICE_UPDATED = "invoice.updated"
    INVOICE_CONFIRMED = "invoice.confirmed"
    INVOICE_POSTED = "invoice.posted"
    INVOICE_DELETED = "invoice.deleted"
    INVOICE_RESET_TO_DRAFT = "invoice.reset"
    INVOICE_CANCELLED = "invoice.cancelled"

    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_POSTED = "payment.refunded"
    PAYMENT_CANCELLED = "payment.cancelled"

    ACCOUNT_MOVE_CREATED = "account_move.created"
    ACCOUNT_MOVE_DELETED = "account_move.deleted"
    ACCOUNT_MOVE_CANCELLED = "account_move.cancelled"
    ACCOUNT_MOVE_POSTED = "account_move.posted"

