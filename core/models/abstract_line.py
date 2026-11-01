from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from decimal import Decimal, ROUND_HALF_UP



class PricedLineMixin(models.Model):
    """The pure pricing/tax math shared by anything that prices a product:
    order lines AND accounting lines. Deliberately does NOT carry
    qty_fulfilled/qty_returned/qty_invoiced or invoice-policy tracking --
    those describe an ORDER line's life cycle (has it been shipped yet, has
    it been invoiced yet), which is meaningless for an invoice line itself
    (an invoice line doesn't get "fulfilled") and meaningless for a plain
    accounting line (a receivable line has no product at all)."""
    price_unit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     validators=[MinValueValidator(Decimal('0'))])
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                           validators=[MinValueValidator(0), MaxValueValidator(100)])
    taxes = models.ManyToManyField('accounting.Tax', blank=True)

    class Meta:
        abstract = True

    def get_discounted_unit_price(self):
        if self.price_unit is None:
            return Decimal('0')
        multiplier = (Decimal('100') - self.discount_percent) / Decimal('100')
        return self.price_unit * multiplier

    def get_subtotal(self):
        qty = getattr(self, 'quantity', None) or Decimal('0')
        return self.get_discounted_unit_price() * qty

    def discounted_unit_price_rounded(self):
        return self.get_discounted_unit_price().quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def subtotal(self):
        return self.get_subtotal().quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def compute_taxes(self, tax_use=None):
        """tax_use='SALE'/'PURCHASE' rejects taxes of the other use (see TaxCalculatorService)."""
        from core.services.tax_engine import TaxCalculatorService
        subtotal = self.get_subtotal()
        quantity = getattr(self, 'quantity', Decimal('1')) or Decimal('1')
        taxes = list(self.taxes.all().order_by('sequence')) if self.pk else []
        return TaxCalculatorService.calculate_line_taxes(
            subtotal=subtotal, quantity=quantity, taxes=taxes, tax_use=tax_use)


class FulfillmentTrackingMixin(models.Model):
    """Order-lifecycle tracking: how much of this ORDER line has been
    physically fulfilled, returned, and invoiced so far. Belongs on
    SalesOrderLine / PurchaseOrderLine / ReturnLine -- lines that live for
    the life of an order and get progressively actioned. Does NOT belong on
    AccountMoveLine: an invoice line is the record of "this much was
    invoiced", not a thing that itself has a qty_invoiced."""
    qty_fulfilled = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_returned = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_invoiced = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        abstract = True

    @property
    def fulfilled_quantity(self):
        return max(self.qty_fulfilled - self.qty_returned, Decimal('0.00'))

    @property
    def remaining_quantity(self):
        return max(self.quantity - self.fulfilled_quantity, Decimal('0.00'))

    @property
    def unfulfilled_returnable(self):
        return max(self.quantity - self.fulfilled_quantity, Decimal('0.00'))

    @property
    def invoice_policy(self):
        return getattr(self.product, self._invoice_policy_field, 'order')

    @property
    def _invoice_policy_field(self):
        raise NotImplementedError(f'{type(self).__name__} must implement _invoice_policy_field')

    @property
    def invoice_target_quantity(self):
        if self.invoice_policy in ('delivery', 'receive'):
            return self.fulfilled_quantity
        return self.quantity

    @property
    def qty_to_invoice(self):
        return max(self.invoice_target_quantity - self.qty_invoiced, Decimal('0.00'))

    @property
    def invoice_state(self):
        target = self.invoice_target_quantity
        if target <= Decimal('0.00'):
            return 'no'
        if self.qty_invoiced >= target:
            return 'invoiced'
        if self.qty_to_invoice > Decimal('0.00'):
            return 'to_invoice'
        return 'no'


class AbstractOrderLine(PricedLineMixin, FulfillmentTrackingMixin):
    """Base for SalesOrderLine / PurchaseOrderLine: a line that is placed,
    then progressively fulfilled, returned and invoiced over its lifetime."""
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('1'))])
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    product_uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+', help_text="Defaults to the product's storage UoM.")
    description = models.CharField(max_length=255)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.product_id and not self.product_uom_id:
            self.product_uom_id = self.product.uom_id
        super().save(*args, **kwargs)


class InvoiceableOrderLineMixin(models.Model):
    """
    Adds the reverse link to InvoiceLine, for order-line models that
    can be invoiced (SalesOrderLine, PurchaseOrderLine). NOT used by
    InvoiceLine itself — InvoiceLine is the target of this relation,
    not a source line.
    """
    invoice_lines = GenericRelation(
        'accounting.AccountMoveLine',
        content_type_field='source_line_type',
        object_id_field='source_line_id',
        related_query_name='invoice_source_line',
    )

    class Meta:
        abstract = True