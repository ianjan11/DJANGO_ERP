from datetime import datetime, timedelta
from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from accounting.services import Period_validators

class PartialReconcile(models.Model):
    """
    FIX: Replaced Reconcile / ReconcileLine with Odoo's partial reconcile pattern.
    Each row pairs one debit line against one credit line with a reconciled amount.
    This correctly handles partial payments, over-payments, and currency differences.
    The old model had a circular FK (JournalLine → ReconcileLine → JournalLine).
    """

    company = models.ForeignKey(
        'core.Company',
        on_delete=models.PROTECT,
        related_name="partial_reconciliations",
    )

    debit_line = models.ForeignKey("accounting.AccountMoveLine", on_delete=models.CASCADE,
                                   related_name='matched_debit_ids')
    credit_line = models.ForeignKey("accounting.AccountMoveLine", on_delete=models.CASCADE,
                                    related_name='matched_credit_ids')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    # For foreign-currency reconciliation
    amount_currency = models.DecimalField(max_digits=15, decimal_places=2,
                                          default=Decimal('0'))
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT,
                                 null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    def clean(self):
        if self.debit_line_id == self.credit_line_id:
            raise ValidationError("A line cannot be reconciled against itself.")

        if self.debit_line.account_id != self.credit_line.account_id:
            raise ValidationError(
                "Both lines must be on the same account to reconcile. "
                f"Got {self.debit_line.account} and {self.credit_line.account}."
            )
        if self.amount <= 0:
            raise ValidationError("Reconciled amount must be positive.")



    def __str__(self):
        return f"Reconcile {self.debit_line_id} ↔ {self.credit_line_id} : {self.amount}"

