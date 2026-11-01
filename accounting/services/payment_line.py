from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from accounting.models import (
    PaymentInvoiceLine,
)



# ---------------------------------------------------------------------------
# Payment allocation
# ---------------------------------------------------------------------------



def create_payment_line(payment, invoice_move, amount: Decimal) -> PaymentInvoiceLine:
    """
    Allocate part of a draft payment to a specific invoice.

    `amount` must be in company currency — same convention as
    invoice_move.amount_residual and payment.amount_company_currency.
    Callers are responsible for converting any user-entered,
    invoice/payment-currency figure before calling this function.

    - Call before payment.confirm() for known-invoice payments.
    - For prepayments, use reconcile_against_invoice() after confirmation.

    Rules enforced here (PaymentInvoiceLine.clean() also checks these):
        • Payment must be in draft core.
        • invoice_move must be a posted invoice or credit note.
        • amount must not exceed invoice residual.
        • Total allocations must not exceed payment amount (company currency).
        • Direction must match (INCOMING ↔ customer docs, OUTGOING ↔ vendor docs).
    """
    if payment.state != "draft":
        raise ValidationError(
            "Cannot add allocations to a payment that is not in draft."
        )

    valid_move_types = ("out_invoice", "in_invoice", "out_refund", "in_refund")
    if invoice_move.move_type not in valid_move_types:
        raise ValidationError(
            f"'{invoice_move.name}' is not an invoice or credit note "
            f"(move_type='{invoice_move.move_type}')."
        )

    if invoice_move.state != "posted":
        raise ValidationError(
            f"Invoice '{invoice_move.name}' is not posted."
        )

    if invoice_move.amount_residual <= Decimal("0"):
        raise ValidationError(
            f"Invoice '{invoice_move.name}' is already fully paid."
        )

    if amount <= Decimal("0"):
        raise ValidationError("Allocated amount must be positive.")

    if amount > invoice_move.amount_residual:
        raise ValidationError(
            f"Cannot allocate {amount}. "
            f"Invoice residual is {invoice_move.amount_residual}."
        )

    # Group by Sub-ledger
    customer_moves = ("out_invoice", "out_refund")
    supplier_moves = ("in_invoice", "in_refund")

    # 1. Partner Type Check (Ensures isolation)
    if payment.partner_type == 'customer' and invoice_move.move_type not in customer_moves:
        raise ValidationError("Customer payments must link to Customer Invoices or Credit Notes.")

    if payment.partner_type == 'supplier' and invoice_move.move_type not in supplier_moves:
        raise ValidationError("Supplier payments must link to Vendor Bills or Credit Notes.")

    # 2. Direction Guard (The "Money Flow" check)
    # Customer: Invoice = INCOMING, Refund = OUTGOING
    if invoice_move.move_type == 'out_invoice' and payment.payment_type != 'INCOMING':
        raise ValidationError("Payments for customer invoices must be INCOMING.")

    if invoice_move.move_type == 'out_refund' and payment.payment_type != 'OUTGOING':
        raise ValidationError("Refunds to customers must be OUTGOING payments.")

    # Supplier: Bill = OUTGOING, Refund = INCOMING
    if invoice_move.move_type == 'in_invoice' and payment.payment_type != 'OUTGOING':
        raise ValidationError("Payments for vendor bills must be OUTGOING.")

    if invoice_move.move_type == 'in_refund' and payment.payment_type != 'INCOMING':
        raise ValidationError("Refunds from vendors must be INCOMING payments.")

    # Total allocation guard — compared in company currency throughout
    existing_total = (
        payment.invoice_allocations
        .aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )


    if existing_total + amount > payment.amount_company_currency:
        remaining = payment.amount_company_currency - existing_total
        raise ValidationError(
            f"Cannot allocate {amount}. "
            f"Only {remaining} of this payment remains unallocated."
        )

    line = PaymentInvoiceLine(
        payment      = payment,
        invoice_move = invoice_move,
        amount       = amount,
    )
    line.full_clean()
    line.save()
    return line