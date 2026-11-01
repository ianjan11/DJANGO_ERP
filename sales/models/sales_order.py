from decimal import Decimal
from functools import cached_property

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from core.models import AbstractOrderLine
from core.models.abstract_line import InvoiceableOrderLineMixin
from core.services.tax_engine import TaxCalculatorService
from inventory.models import StockQuant


class SalesOrder(models.Model):
    STATUS = (
        ('DRAFT', 'Quotation'),
        ('SENT', 'Quotation Sent'),
        ('CONFIRMED', 'Sales Order'),
        ('DONE', 'Locked/Done'),
        ('CANCELLED', 'Cancelled'),
    )
    DELIVERY_STATUS = (
        ('NOT_DELIVERED', 'Not Delivered'),
        ('PARTIALLY_DELIVERED', 'Partially Delivered'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    )
    PAYMENT_STATE = (
        ('not_paid', 'Not Paid'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
    )

    INVOICE_STATUS = (
        ("no", "Nothing to Invoice"),
        ("to_invoice", "To Invoice"),
        ("invoiced", "Fully Invoiced"),
    )

    # ------------------------ identity / lifecycle -------------------
    order_number = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        default=None,
        help_text="Assigned from a per-company sequence when confirmed",
    )
    status = models.CharField(max_length=10, choices=STATUS, default='DRAFT')
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS, default='NOT_DELIVERED')

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sales_orders_created',
    )
    issue_date = models.DateField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    # ------------------------ parties -------------------
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='sales_orders')
    partner = models.ForeignKey('core.Partner', on_delete=models.PROTECT, related_name='sales_orders',
                                 null=True, blank=True)

    invoice_status = models.CharField(
        max_length=20, choices=INVOICE_STATUS, default="no"
    )

    fulfillment_location = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='sales_orders',
        help_text="Warehouse fulfilling this sales order",

    )

    product_uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+')

    # ------------------------ money -------------------
    currency = models.ForeignKey('core.Currency', on_delete=models.PROTECT, related_name='sales_orders')

    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))

    payment_state = models.CharField(max_length=20, choices=PAYMENT_STATE, default='not_paid')
    payment_term = models.ForeignKey(
        'accounting.PaymentTerm', on_delete=models.PROTECT, related_name='sales_orders',
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issue_date', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'order_number'],
                condition=Q(order_number__isnull=False),
                name='uniq_sales_order_number_per_company',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['company', 'issue_date']),
            models.Index(fields=['partner', 'status']),
        ]



    def __str__(self):
        return self.order_number or f"Draft SO #{self.pk} — {self.partner}"

    # ---- Aggregation ----

    def has_items(self):
        return self.lines.exists()

    def compute_amounts(self):
        """
        Single-pass computation using TaxCalculatorService.
        Returns (untaxed, tax, total) in a single tuple.
        """
        lines = list(self.lines.prefetch_related('taxes').all())
        summary = TaxCalculatorService.calculate_document_taxes(lines)

        return (
            summary['total_untaxed'],
            summary['total_tax'],
            summary['total_gross']
        )

    @cached_property
    def tax_summary(self) -> dict:
        """
        Calculates taxes ONLY ONCE per instance execution.
        Subsequent calls return the cached dictionary immediately.
        """
        lines = list(self.lines.prefetch_related('taxes').all())
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
        return sum(
            (item.profit() for item in self.lines.all() if item.profit() is not None),
            Decimal('0.00'),
        )

    # ---- Delivery status rollup ----

    @transaction.atomic
    def try_complete_from_delivery(self):
        if self.delivery_status in ('DELIVERED', 'CANCELLED'):
            return  # terminal states

        all_statuses = set(self.deliveries.values_list('status', flat=True))
        if not all_statuses:
            return  # no deliveries at all yet

        active_statuses = all_statuses - {'CANCELLED'}

        if not active_statuses:
            new_status = 'CANCELLED'  # every delivery on this order was cancelled
        elif active_statuses == {'PENDING'}:
            return  # nothing to report yet
        elif 'PENDING' in active_statuses and 'COMPLETED' in active_statuses:
            new_status = 'PARTIALLY_DELIVERED'
        else:
            new_status = 'DELIVERED'  # only COMPLETED left among active deliveries

        if new_status == self.delivery_status:
            return

        self.delivery_status = new_status
        update_fields = ['delivery_status']
        if new_status == 'DELIVERED':
            self.delivered_at = timezone.now()
            update_fields.append('delivered_at')

        self.save(update_fields=update_fields)

    # ---- Confirmation ----


    def _compute_invoice_status(self):
        line_states = [
            "invoiced" if l.invoiced_quantity >= l.quantity
            else "to_invoice" if l.invoiced_quantity > 0
            else "no"
            for l in self.lines.all()
        ]
        if all(s == "invoiced" for s in line_states):
            self.invoice_status = "invoiced"
        elif any(s in ("to_invoice", "invoiced") for s in line_states):
            self.invoice_status = "to_invoice"
        else:
            self.invoice_status = "no"


class SalesOrderLine(AbstractOrderLine, InvoiceableOrderLineMixin):
    sales_order = models.ForeignKey(
        'sales.SalesOrder',
        on_delete=models.CASCADE,
        related_name='lines',
    )
    sequence = models.PositiveIntegerField(default=10)

    quant = models.ForeignKey(
        'inventory.StockQuant',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    product_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    stock_move = models.OneToOneField(
        'inventory.StockMove',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sales_order_item',
    )

    class Meta:
        ordering = ['sequence', 'pk']


    def __str__(self):
        return f"{self.product.name} × {self.quantity}"

    # ---- Amounts (computed, not stored — see InvoiceLine discussion) ----

    @property
    def amount_untaxed(self) -> Decimal:
        return self.get_subtotal()

    @property
    def amount_tax(self) -> Decimal:

        base, tax_amount, lines, totals = self.compute_taxes()

        return tax_amount

    @property
    def amount_total(self) -> Decimal:
        return self.amount_untaxed + self.amount_tax

    # ---- Costing ----

    def total_cost(self):
        if not self.product_cost or not self.quantity:
            return Decimal('0')
        return self.product_cost * self.quantity

    def profit(self):
        if self.product_cost is None:
            return None
        return self.amount_untaxed - self.total_cost()

    # ---- Validation ----

    def clean(self):
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({'quantity': "Quantity cannot be negative."})

        if self.price_unit is not None and self.price_unit < 0:
            raise ValidationError({'price_unit': "Price cannot be negative."})

        if self.discount_percent is not None and self.discount_percent < 0:
            raise ValidationError({'discount_percent': "Discount cannot be negative."})

        if self.quant_id and self.sales_order_id and not self.sales_order.fulfillment_location:
            raise ValidationError({'quant': "Sales order must have a source location."})

    @property
    def _invoice_policy_field(self):
        return "sales_invoicing_method"



