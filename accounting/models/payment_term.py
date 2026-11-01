from datetime import datetime, timedelta
from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from accounting.services import Period_validators


class PaymentTerm(models.Model):
    company = models.ForeignKey(
        'core.Company',
        on_delete=models.CASCADE,
        related_name="payment_terms",
    )

    name = models.CharField(max_length=50)
    note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class PaymentTermLine(models.Model):
    """
    NEW: Supports installment-style terms (e.g. 30% now, 70% in 30 days).
    The old single-row model could only express "Net N days".
    """
    COMPUTATION_TYPES = [
        ('PERCENT', 'Percent of balance'),
        ('FIXED', 'Fixed amount'),
        ('BALANCE', 'Remaining balance'),   # always the last line
    ]
    payment_term = models.ForeignKey('accounting.PaymentTerm', on_delete=models.CASCADE,
                                     related_name='lines')
    sequence = models.IntegerField(default=10)
    computation_type = models.CharField(max_length=20, choices=COMPUTATION_TYPES,
                                        default='BALANCE')
    value = models.DecimalField(max_digits=6, decimal_places=2, default=0,
                                help_text="Percent (0-100) or fixed amount, ignored for BALANCE")
    days = models.IntegerField(default=0, help_text="Days from invoice date")
    discount_days = models.IntegerField(null=True, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2,
                                           null=True, blank=True)

    class Meta:
        ordering = ['sequence']

    def __str__(self):
        return f"{self.payment_term.name} - line {self.sequence}"

    def compute_amount(self, total_amount):
        if self.computation_type == 'PERCENT':
            return total_amount * (self.value / Decimal('100'))
        elif self.computation_type == 'FIXED':
            return Decimal(str(self.value))
        elif self.computation_type == 'BALANCE':
            return None
        else:
            raise ValidationError(f"Unknown computation type: {self.computation_type}")
