from datetime import datetime, timedelta
from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from accounting.services import Period_validators




class PaymentInvoiceLine(models.Model):
    """
    Explicit allocation: which invoice(s) this payment settles and how much.

    Created BEFORE confirm() — records intent only, no GL effect.
    On Payment.confirm(), PartialReconcile rows are built from these.

    Rules:
    - INCOMING → out_invoice / out_refund only
    - OUTGOING → in_invoice  / in_refund  only
    - amount cannot exceed invoice.amount_residual
    - sum of all allocations cannot exceed payment.amount
    """

    payment = models.ForeignKey(
        "accounting.Payment",
        on_delete=models.CASCADE,
        related_name='invoice_allocations',
    )
    invoice_move = models.ForeignKey(
        "accounting.AccountMove",
        on_delete=models.PROTECT,
        related_name='payment_allocations',
        limit_choices_to={
            'move_type__in': [
                'out_invoice', 'in_invoice',
                'out_refund',  'in_refund',
            ]
        },
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return (
            f"{self.payment.payment_number or 'DRAFT'} → "
            f"{self.invoice_move.name}: {self.amount}"
        )

    def clean(self):
        if not self.amount or self.amount <= 0:
            raise ValidationError("Allocated amount must be positive.")

        if self.invoice_move:
            if self.invoice_move.state != 'posted':
                raise ValidationError(
                    f"Invoice '{self.invoice_move.name}' is not posted."
                )
            if self.invoice_move.amount_residual <= 0:
                raise ValidationError(
                    f"Invoice '{self.invoice_move.name}' is already fully paid."
                )
            if self.amount > self.invoice_move.amount_residual:
                raise ValidationError(
                    f"Allocated {self.amount} exceeds invoice residual "
                    f"{self.invoice_move.amount_residual}."
                )

            if self.payment:
                # Sub-ledger categories
                customer_moves = ('out_invoice', 'out_refund')
                vendor_moves = ('in_invoice', 'in_refund')

                # 1. Partner/Sub-ledger Isolation
                # Ensure a Customer payment doesn't hit a Vendor bill
                if self.payment.partner_type == 'customer' and self.invoice_move.move_type not in customer_moves:
                    raise ValidationError("Customer payments must be linked to customer invoices or credit notes.")

                if self.payment.partner_type == 'supplier' and self.invoice_move.move_type not in vendor_moves:
                    raise ValidationError("Vendor payments must be linked to vendor bills or credit notes.")

                # 2. Direction Validation
                move_type = self.invoice_move.move_type
                pay_type = self.payment.payment_type

                # Logic:
                # INCOMING is for Customer Invoices OR Vendor Refunds
                # OUTGOING is for Vendor Bills OR Customer Refunds

                if pay_type == 'INCOMING' and move_type not in ('out_invoice', 'in_refund'):
                    raise ValidationError(
                        f"INCOMING payment cannot be applied to a {move_type}. "
                        "It must be a Customer Invoice or a Vendor Credit Note."
                    )

                if pay_type == 'OUTGOING' and move_type not in ('in_invoice', 'out_refund'):
                    raise ValidationError(
                        f"OUTGOING payment cannot be applied to a {move_type}. "
                        "It must be a Vendor Bill or a Customer Credit Note."
                    )
            existing_total = (
                PaymentInvoiceLine.objects
                .filter(payment=self.payment)
                .exclude(pk=self.pk)
                .aggregate(s=Sum('amount'))['s']
                or Decimal('0')
            )
            if existing_total + self.amount > self.payment.amount_company_currency:
                remaining = self.payment.amount - existing_total
                raise ValidationError(
                    f"Allocation of {self.amount} would exceed payment amount "
                    f"{self.payment.amount}. Remaining allocatable: {remaining}."
                )
