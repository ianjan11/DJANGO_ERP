from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from django.utils.functional import cached_property

class AccountMove(models.Model):
    class MoveType(models.TextChoices):
        OUT_INVOICE = 'out_invoice', 'Customer Invoice'
        OUT_REFUND = 'out_refund', 'Customer Credit Note'
        IN_INVOICE = 'in_invoice', 'Vendor Bill'
        IN_REFUND = 'in_refund', 'Vendor Credit Note'
        PAYMENT = 'payment', 'Payment'
        ENTRY = 'entry', 'Journal Entry'

    class State(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        POSTED = 'posted', 'Posted'
        CANCELLED = 'cancelled', 'Cancelled'

    class PaymentState(models.TextChoices):
        NOT_PAID = 'not_paid', 'Not Paid'
        PARTIAL = 'partial', 'Partially Paid'
        PAID = 'paid', 'Paid'

    INVOICE_TYPES = (MoveType.OUT_INVOICE, MoveType.OUT_REFUND, MoveType.IN_INVOICE, MoveType.IN_REFUND)
    PAYMENT_DIRECTION = {
        'out_invoice': 'INCOMING', 'in_refund': 'INCOMING',
        'in_invoice': 'OUTGOING', 'out_refund': 'OUTGOING',
    }

    name = models.CharField(max_length=50, blank=True, null=True,
                            help_text='Auto-generated sequence number, e.g. INV/2026/0001')
    move_type = models.CharField(max_length=20, choices=MoveType.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)

    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='moves_created')
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                  null=True, blank=True, related_name='+')

    partner = models.ForeignKey('core.Partner', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='account_moves')
    currency = models.ForeignKey('core.Currency', on_delete=models.PROTECT)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='account_moves')
    journal = models.ForeignKey('accounting.Journal', on_delete=models.PROTECT, related_name='moves')
    payment_term = models.ForeignKey('accounting.PaymentTerm', on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='moves', help_text='Applicable on invoices only')

    fulfillment_location = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT,
                                             null=True, blank=True, related_name='account_moves')
    origin_reference = models.CharField(max_length=64, blank=True)

    reversal_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='reversal_moves', help_text='Source move this entry reverses')
    reversal_reason = models.CharField(max_length=50, choices=[
        ('cancellation', 'Cancellation'), ('return', 'Customer Return'), ('correction', 'Correction'),
    ], null=True, blank=True)

    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    amount_residual = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    currency_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True,
                                        help_text='Exchange rate to company currency, snapshotted at posting')

    payment_state = models.CharField(max_length=20, choices=PaymentState.choices, default=PaymentState.NOT_PAID)
    reconciled = models.BooleanField(default=False)
    reconciliation_date = models.DateField(null=True, blank=True)

    ref = models.CharField(max_length=100, blank=True, help_text='Invoice number, payment reference, etc.')
    narration = models.TextField(blank=True)

    origin_type = models.CharField(max_length=50, null=True, blank=True)
    origin_id = models.PositiveIntegerField(null=True, blank=True)
    is_prepayment_swap = models.BooleanField(default=False, help_text='True when payment is a prepayment')

    class Meta:
        ordering = ['-issue_date', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['company', 'journal', 'name'], condition=Q(name__isnull=False),
                                    name='account_move_name_per_journal_uniq'),
        ]
        indexes = [
            models.Index(fields=['origin_type', 'origin_id', 'is_prepayment_swap']),
            models.Index(fields=['company', 'state']),
            models.Index(fields=['company', 'move_type', 'issue_date']),
            models.Index(fields=['partner', 'state']),
        ]

    def __str__(self):
        return self.name or f'Draft #{self.pk} ({self.get_move_type_display()})'

    @property
    def is_invoice(self):
        return self.move_type in self.INVOICE_TYPES

    @property
    def payment_direction(self):
        return self.PAYMENT_DIRECTION.get(self.move_type, '')

    def has_items(self):
        return self.lines.exists()

    def clean(self):
        super().clean()
        if self.move_type in ('out_invoice', 'in_invoice') and not self.payment_term and not self.due_date:
            raise ValidationError('An invoice must have either a payment term or a due date.')
        if not self.is_invoice and (self.fulfillment_location_id or self.origin_reference):
            raise ValidationError(f'{self.get_move_type_display()} entries do not carry invoice fields '
                                  '(fulfillment_location, origin_reference).')

    @cached_property
    def tax_summary(self) -> dict:
        """Runs tax calculation once per instance; later access reuses this dict."""
        from core.services.tax_engine import TaxCalculatorService
        lines = list(self.lines.filter(line_type=AccountMoveLine.LineType.PRODUCT).prefetch_related('taxes'))
        return TaxCalculatorService.calculate_document_taxes(lines)

    @property
    def total_amount(self):
        return self.tax_summary['total_gross']

    @property
    def untaxed_amount(self):
        return self.tax_summary['total_untaxed']

    @property
    def total_tax(self):
        return self.tax_summary['total_tax']

    def total_profit(self):
        return sum((l.profit() for l in self.lines.all() if hasattr(l, 'profit') and l.profit() is not None),
                   Decimal('0.00'))

    def is_balanced(self):
        totals = self.lines.aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return (totals['debit'] or 0) == (totals['credit'] or 0)


    @property
    def total_debit(self):
        return self.lines.aggregate(debit=Sum('debit'))['debit'] or 0

    @property
    def total_credit(self):
        return self.lines.aggregate(credit=Sum('credit'))['credit'] or 0

    def post(self, user):

        if not self.is_balanced():
            raise ValidationError('Cannot post an unbalanced journal entry.')
        if not self.name:
            self.name = self.journal.get_next_number()

        if self.state != self.State.POSTED:
           self.state = self.State.POSTED

        self.lines.filter(date__isnull=True).update(date=self.issue_date)
        self.posted_by = user
        self.posted_at = timezone.now()
        self.save(update_fields=['state', 'posted_by', 'posted_at', 'name'])

    def update_residual(self):
        """Recompute residual from actual reconciliations (source of truth)."""
        ar_lines = self.lines.filter(account__allow_reconciliation=True)
        # An invoice also carries GDNI/GRNI clearing lines on reconcilable accounts.
        # Those are matched against delivery/receipt entries, not paid by the
        # customer, so only the control (AR/AP) line counts toward payment state.
        control_lines = ar_lines.filter(line_type=AccountMoveLine.LineType.RECEIVABLE)
        if control_lines.exists():
            ar_lines = control_lines
        total = Decimal('0')
        residual = Decimal('0')
        for line in ar_lines:
            line_amount = line.debit if line.debit > 0 else line.credit
            matched_debit = line.matched_debit_ids.aggregate(s=Sum('amount'))['s'] or Decimal('0')
            matched_credit = line.matched_credit_ids.aggregate(s=Sum('amount'))['s'] or Decimal('0')
            matched = matched_debit + matched_credit
            remaining = max(Decimal('0'), line_amount - matched)
            total += line_amount
            residual += remaining

        self.amount_residual = residual
        self.paid_amount = total - residual
        if residual == 0:
            self.payment_state, self.reconciled = self.PaymentState.PAID, True
        elif self.paid_amount > 0:
            self.payment_state = self.PaymentState.PARTIAL
        else:
            self.payment_state = self.PaymentState.NOT_PAID
        self.save(update_fields=['amount_residual', 'paid_amount', 'payment_state', 'reconciled'])

    def get_already_matched_amount(self, line):
        from accounting.models import PartialReconcile
        matches = PartialReconcile.objects.filter(
            Q(debit_line__move=self, credit_line=line) | Q(credit_line__move=self, debit_line=line)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return matches

    def get_origin_owner(self):
        if self.origin_type == 'payment' and self.origin_id:
            from accounting.models import Payment
            return Payment.objects.filter(id=self.origin_id).first()
        return None

    def sync_origin_reconciliation_state(self, payment_state, residual):
        owner = self.get_origin_owner()
        if owner is not None:
            owner.apply_reconciliation_state(payment_state, residual)


from core.models.abstract_line import PricedLineMixin
class AccountMoveLine(PricedLineMixin, models.Model):
    """One posted line: either a *product* line (invoice: has product,
    quantity, UoM, price, discount, taxes) or a plain *accounting* line
    (receivable/payable, tax, rounding, or a manual journal-entry line: just
    account/debit/credit/partner/memo, no product at all). `line_type`
    decides which fields are meaningful; product fields stay nullable so a
    non-product line never has to fake them.
    """
    class LineType(models.TextChoices):
        PRODUCT = 'product', 'Product'
        TAX = 'tax', 'Tax'
        RECEIVABLE = 'receivable', 'Receivable/Payable'
        ROUNDING = 'rounding', 'Rounding'
        PLAIN = '', 'Journal Entry Line'

    move = models.ForeignKey(AccountMove, on_delete=models.CASCADE, related_name='lines')
    line_type = models.CharField(max_length=12, choices=LineType.choices, blank=True, default=LineType.PLAIN)
    sequence = models.PositiveIntegerField(default=10)

    account = models.ForeignKey('accounting.Account', on_delete=models.PROTECT, related_name='+')
    partner = models.ForeignKey('core.Partner', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    original_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    foreign_currency = models.ForeignKey('core.Currency', on_delete=models.PROTECT, null=True, blank=True,
                                         related_name='+')
    memo = models.CharField(max_length=200, blank=True, null=True)
    date = models.DateField(null=True, blank=True, help_text='Defaults to the move date if blank')
    reconciled = models.BooleanField(default=False)

    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='+')
    quantity = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    product_uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+')
    description = models.CharField(max_length=255, blank=True)

    quant = models.ForeignKey('inventory.StockQuant', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='+')
    stock_move = models.OneToOneField('inventory.StockMove', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='invoice_items')

    source_line_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name='+')
    source_line_id = models.PositiveIntegerField(null=True, blank=True)
    source_line = GenericForeignKey('source_line_type', 'source_line_id')

    class Meta:
        ordering = ['move', 'sequence', 'pk']
        indexes = [
            models.Index(fields=['move', 'account']),
            models.Index(fields=['account', 'date']),
            models.Index(fields=['source_line_type', 'source_line_id']),
        ]

    def __str__(self):
        if self.line_type == self.LineType.PRODUCT:
            return f'{self.move_id} \u00b7 {self.product} \u00d7 {self.quantity}'
        return f'{self.move_id} \u00b7 {self.account} (debit {self.debit} / credit {self.credit})'

    @property
    def quantity_in_storage_uom(self):
        """Mirrors StockMove.quantity_in_storage_uom, for matching this line's
        billed quantity against the stock that actually moved (`quant`/`stock_move`)."""
        if self.quantity is None or not self.product_id:
            return None
        uom = self.product_uom or self.product.uom
        return uom.convert_to(self.quantity, self.product.uom)

    def clean(self):
        super().clean()
        if self.line_type == self.LineType.PRODUCT:
            if not self.product_id or self.quantity is None or self.price_unit is None:
                raise ValidationError('A product line needs a product, quantity and unit price.')
            if self.product_uom_id and self.product_uom.category_id != self.product.uom.category_id:
                raise ValidationError(
                    f'"{self.product_uom}" isn\'t the same dimension as {self.product.name}\'s '
                    f'storage Unit of Measure ("{self.product.uom}").')
        elif self.product_id or self.quantity is not None:
            raise ValidationError(f'A "{self.get_line_type_display()}" line cannot carry a product/quantity '
                                  '-- only a "product" line can.')

    def save(self, *args, **kwargs):
        if self.line_type == self.LineType.PRODUCT and self.product_id and not self.product_uom_id:
            self.product_uom_id = self.product.uom_id
        if self.date is None and self.move_id:
            self.date = self.move.issue_date
        self.clean()
        super().save(*args, **kwargs)