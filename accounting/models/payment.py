from django.conf import settings
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from accounting.services import Period_validators


class Payment(models.Model):
    """
    Mirrors Odoo's account.payment.

    Architecture:
    - Payment stores the *intent*: who, how much, which direction, method.
    - All GL effect lives in account_move (created on confirm()).
    - core is derived from account_move.core — not stored independently.
    - payment_state (paid/partial/not_paid) is a cache recomputed from
      PartialReconcile rows on the move's outstanding AR/AP line.
    - The outstanding line is the AR line (INCOMING) or AP line (OUTGOING)
      that sits waiting to be matched against an invoice.
    """

    # ------------------------------------------------------------------
    # Payment direction  (Odoo: payment_type)
    # INCOMING = money comes in  → debit Bank/Cash, credit AR
    # OUTGOING = money goes out  → debit AP,        credit Bank/Cash
    # TRANSFER = internal move between two journals (petty-cash top-up etc.)
    # ------------------------------------------------------------------
    PAYMENT_TYPES =[
        ('INCOMING', 'Incoming'),
        ('OUTGOING', 'Outgoing'),
        ('TRANSFER', 'Internal Transfer'),
    ]

    # ------------------------------------------------------------------
    # How the funds actually moved  (Odoo: payment_method_id)
    # ------------------------------------------------------------------
    PAYMENT_METHODS = [
        ('MANUAL',        'Manual'),           # cash hand-over, generic
        ('CHECK',         'Check'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE',        'Mobile Money'),     # M-Pesa / Tigo-Pesa common in TZ
    ]

    # ------------------------------------------------------------------
    # State — derived from account_move, but cached here for fast queries
    # Do NOT set these directly; use confirm() / cancel() / _sync_state()
    # ------------------------------------------------------------------
    STATE_CHOICES = [
        ('draft',      'Draft'),
        ('posted',     'Posted'),       # move confirmed, GL lines exist
        ('reconciled', 'Reconciled'),   # outstanding line fully matched
        ('cancelled',  'Cancelled'),
    ]

    PAYMENT_STATE_CHOICES = [
        ('not_paid', 'Not Paid'),
        ('partial',  'Partially Paid'),
        ('paid',     'Paid / Matched'),
    ]

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    payment_number = models.CharField(
        max_length=50, unique=True, blank=True, null=True, editable=False,
        help_text="Auto-assigned from journal sequence on confirm()",
    )
    date = models.DateField()
    company = models.ForeignKey(
        'core.Company', on_delete=models.CASCADE, related_name='payments',
    )

    # ------------------------------------------------------------------
    # Counterparty
    # partner is required for INCOMING / OUTGOING.
    # For TRANSFER: it is blank — the two journals are the counterparties.
    # ------------------------------------------------------------------
    partner = models.ForeignKey(
        'core.Partner', on_delete=models.PROTECT,
        help_text="Required for INCOMING / OUTGOING; leave blank for TRANSFER",
    )
    partner_type = models.CharField(
        max_length=20,
        choices=[('customer', 'Customer'), ('supplier', 'Supplier')],
        help_text="Drives which AR/AP account is used. Auto-set from payment_type.",
    )

    # ------------------------------------------------------------------
    # Direction & method
    # ------------------------------------------------------------------
    payment_type   = models.CharField(max_length=20, choices=PAYMENT_TYPES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='MANUAL')

    # ------------------------------------------------------------------
    # Amount & currency
    # amount         — always positive (direction is encoded in payment_type)
    # currency       — the payment's own currency (may differ from company CCY)
    # amount_company — equivalent in company currency (set on confirm())
    # ------------------------------------------------------------------
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.ForeignKey(
        'core.Currency', on_delete=models.PROTECT,
        help_text="Currency of this payment",
    )
    amount_company_currency = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0'),
        help_text="Amount in company currency — computed from currency_rate on confirm()",
    )
    currency_rate = models.DecimalField(
        max_digits=12, decimal_places=6,
        null=True, blank=True,
        help_text="Exchange rate to company currency at the time of posting",
    )

    # ------------------------------------------------------------------
    # Journal  (the bank / cash account that moves)
    # For TRANSFER: journal = source, destination_journal = target
    # ------------------------------------------------------------------
    journal = models.ForeignKey(
        'accounting.Journal', on_delete=models.PROTECT,
        limit_choices_to={'type__in': ['BANK', 'CASH']},
        related_name='payments',
        help_text="Bank or cash journal the payment flows through",
    )
    destination_journal = models.ForeignKey(
        'accounting.Journal', on_delete=models.PROTECT,
        null=True, blank=True,
        limit_choices_to={'type__in': ['BANK', 'CASH']},
        related_name='payments_received',
        help_text="Target journal for TRANSFER payments only",
    )

    # ------------------------------------------------------------------
    # Reference & notes
    # ------------------------------------------------------------------
    ref = models.CharField(
        max_length=100, blank=True,
        help_text="Cheque number, wire reference, M-Pesa transaction ID, etc.",
    )
    memo = models.TextField(blank=True)
    is_prepayment = models.BooleanField(
        default=False,
        help_text="True when paid before an invoice exists (creates a credit on AR/AP)",
    )

    # ------------------------------------------------------------------
    # GL link — the single AccountMove this payment owns
    # Created by confirm(); destroyed only if payment is cancelled.
    # ------------------------------------------------------------------
    account_move = models.OneToOneField(
        'accounting.AccountMove', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payment',
    )

    reversal_move = models.OneToOneField(
        'accounting.AccountMove', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reversal_payment',
    )

    # ------------------------------------------------------------------
    # State cache  — synced from account_move in _sync_state()
    # ------------------------------------------------------------------
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default='draft',
    )
    payment_state = models.CharField(
        max_length=20, choices=PAYMENT_STATE_CHOICES, default='not_paid',
        help_text="Cache of reconciliation status — recompute via _recompute_payment_state()",
    )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='payments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-date', '-id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_amount_gt_zero",
            )
        ]

    def __str__(self):
        return f"{self.payment_number or 'DRAFT'} | {self.partner} | {self.amount} {self.currency}"

    # ==================================================================
    # Validation
    # ==================================================================

    def clean(self):
        # Partner required for customer / vendor payments
        if self.payment_type in ('INCOMING', 'OUTGOING') and not self.partner_id:
            raise ValidationError("Partner is required for customer and vendor payments.")

        # Destination journal required only for transfers
        if self.payment_type == 'TRANSFER' and not self.destination_journal:
            raise ValidationError("A destination journal is required for internal transfers.")
        if self.payment_type != 'TRANSFER' and self.destination_journal:
            raise ValidationError("Destination journal is only allowed on TRANSFER payments.")

        # Amount must be positive
        if self.amount is None or self.amount <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        if self.company_id and self.date:
          Period_validators.PeriodValidator.validate_period(self.company,self.date)

    @property
    def allocated_amount(self ):
        return self.amount_company_currency - self.residual_amount

    # ==================================================================
    # Workflow
    # ==================================================================
    def confirm(self, request):
        """
        Transitions DRAFT → POSTED.
        """
        self.full_clean()

        with transaction.atomic():
            if not self.payment_number:
                self.payment_number = self.journal.get_next_payment_number()

            from accounting.services.payments_service.payment_move_service import (
                build_payment_account_move,
            )
            move = build_payment_account_move(self, request.user)
            self.account_move = move

            self.posted_at = timezone.now()
            self.save(update_fields=['state', 'posted_at', 'account_move', 'payment_number'])

            from accounting.services.reconciliation_service.reconciliation_service import (
                ReconciliationService,
            )

            line_ids = self.get_reconciliation_line_ids()
            if line_ids:
                ReconciliationService(
                    company=request.company,
                    line_ids=line_ids,
                    user=request.user,
                ).run()

    # ---------------------------------------------------------------------------
    # Payment.residual_amount
    # ---------------------------------------------------------------------------

    @property
    def residual_amount(self):
        """
        How much of this payment's total amount is still unmatched against
        invoices. Company currency throughout.
        """
        if not self.account_move_id:
            return self.amount_company_currency  # not posted yet — nothing matched, full amount available

        from accounting.services.payments_service.payment_helpers import _payment_reconciliation_summary
        lines, reconciled_amount, residual = _payment_reconciliation_summary(self)

        if not lines:
            # posted, but nothing has ever been swapped/matched for this
            # payment — full amount still outstanding
            return self.amount_company_currency

        return residual

    # ==================================================================
    # Internal helpers
    # ==================================================================


    def get_reconciliation_line_ids(self):
        from accounting.models import PaymentInvoiceLine

        application = (
            PaymentInvoiceLine.objects
            .select_related("invoice_move")
            .filter(payment=self)
            .first()
        )

        if not application:
            return []

        invoice_line_ids = list(
            application.invoice_move.lines
            .filter(account__allow_reconciliation=True)
            .values_list("id", flat=True)
        )

        payment_line_ids = list(
            self.account_move.lines
            .filter(account__allow_reconciliation=True)
            .values_list("id", flat=True)
        )

        return invoice_line_ids + payment_line_ids

    # on Payment
    def apply_reconciliation_state(self, payment_state, residual):
        update_fields = []
        if payment_state != self.payment_state:
            self.payment_state = payment_state
            update_fields.append('payment_state')
        if payment_state == 'paid' and self.state != 'reconciled':
            self.state = 'reconciled'
            update_fields.append('state')
        if update_fields:
            self.save(update_fields=update_fields)


    def save(self, *args, **kwargs):
        from core.services.currency_exchange_service import _get_rate

        if self.amount is not None and self.currency_id and self.company_id:
            if self.currency_id == self.company.currency_id:
                self.currency_rate = Decimal('1')
                self.amount_company_currency = self.amount
            else:
                rate = _get_rate(
                    company=self.company,
                    currency=self.currency,
                    date=self.date,
                )
                self.currency_rate = rate
                self.amount_company_currency = (
                        self.amount * rate
                ).quantize(Decimal('0.01'))

        super().save(*args, **kwargs)

