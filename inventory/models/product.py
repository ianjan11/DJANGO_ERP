from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, DecimalField, Q
from django.db.models.functions import Coalesce



class ProductsCategory(models.Model):

    name = models.CharField(max_length=100)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='products_categories')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )

    # Accounting Properties (can be inherited from parent)
    property_valuation_account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="valuation_categories"
    )

    property_stock_input_account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_input_categories"
    )


    property_stock_output_account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_output_categories"
    )

    property_cogs_account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cogs_categories"
    )

    property_price_difference_account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="price_difference_categories"
    )

    # Optional improvements
    is_active = models.BooleanField(default=True)
    complete_name = models.CharField(max_length=255, editable=False)

    class Meta:
        unique_together = ('name', 'parent')  # Prevent duplicate names under same parent
        verbose_name_plural = "Product Categories"

    def __str__(self):
        return self.complete_name

    # -------------------------
    # 🔁 ACCOUNT INHERITANCE
    # -------------------------
    def get_valuation_account(self):
        if self.property_valuation_account:
            return self.property_valuation_account
        if self.parent:
            return self.parent.get_valuation_account()
        return None

    def get_stock_input_account(self):
        if self.property_stock_input_account:
            return self.property_stock_input_account
        if self.parent:
            return self.parent.get_stock_input_account()
        return None


    def get_stock_output_account(self):
        if self.property_stock_output_account:
            return self.property_stock_output_account
        if self.parent:
            return self.parent.get_stock_output_account()
        return None

    def get_cogs_account(self):
        if self.property_cogs_account:
            return self.property_cogs_account

        if self.parent:
            return self.parent.get_cogs_account()

        return None

    def get_price_difference_account(self):
        if self.property_price_difference_account:
            return self.property_price_difference_account

        if self.parent:
            return self.parent.get_price_difference_account()

        return None



    # -------------------------
    # 🌳 HIERARCHY UTILITIES
    # -------------------------
    def get_full_name(self):
        if self.parent:
            return f"{self.parent.get_full_name()} / {self.name}"
        return self.name

    # -------------------------
    # 🔒 VALIDATION
    # -------------------------
    def clean(self):
        # Prevent circular reference
        parent = self.parent
        while parent:
            if parent == self:
                raise ValidationError("Circular category hierarchy detected.")
            parent = parent.parent

    # -------------------------
    # 💾 SAVE OVERRIDE
    # -------------------------
    def save(self, *args, **kwargs):
        self.full_clean()  # ensure validation runs
        self.complete_name = self.get_full_name()
        super().save(*args, **kwargs)


class Product(models.Model):

    PURCHASE_METHOD = (
        ('purchase', 'On ordered quantities'),
        ('receive', 'On received quantities'),
    )

    COSTING_METHODS = (
        ('manual', 'Standard Price'),
        ('fifo', 'First In First Out (FIFO)'),
        ('average', 'Average Cost (AVCO)'),
    )
    PRODUCT_TYPES = (
        ('storable', 'Storable Product'),   # Paints, Pipes (Tracked in Stock)
        ('service', 'Service'),             # Labor, Consultancy (Not in Stock)
        ('consumable', 'Consumable'),       # Cleaning supplies (physical, not tracked as inventory)
    )

    INVOICING_METHOD_CHOICES = (
        ('order', 'On Order \u2014 invoiceable immediately, no fulfillment required'),
        ('delivery', 'On Delivery \u2014 invoiceable only once shipped to customer'),
    )

    REFUND_METHOD_CHOICES = (
        ('receiving', 'On Receiving - invoiceable immediately after receiving'),
    )

    VALUATION_METHODS = (
        ('manual', 'Manual'),
        ('automated', 'Automated'),
    )

    class Tracking(models.TextChoices):
        NONE = 'none', 'No Tracking'
        LOT = 'lot', 'By Lots'
        SERIAL = 'serial', 'By Unique Serial Number'

    # basic information
    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=100, unique=True)
    # Identifies *what the item is* for scanning (EAN13/UPC...). Different from `sku`,
    # which is your own internal reference and isn't necessarily what's printed on the item.
    barcode = models.CharField(max_length=64, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='products')
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPES, default='storable')
    category = models.ForeignKey('inventory.ProductsCategory', on_delete=models.PROTECT)

    # How this product is tracked in the warehouse. Only meaningful for stockable
    # products -- a service can't be lot-tracked because it never sits in a location.
    tracking = models.CharField(max_length=10, choices=Tracking.choices, default=Tracking.NONE)
    # The single source of truth for StockQuant.quantity. Replaces the old free-text
    # `unit_of_measure` string, which couldn't convert kg <-> g or dozen <-> unit.
    uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, related_name='products_stock',
                            null=True, blank=True, verbose_name='Storage Unit of Measure')
    # UoM used when buying (kg, dozen...). Defaults to `uom`. Must be the same dimension.
    uom_po = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, related_name='products_purchase',
                               null=True, blank=True, verbose_name='Purchase Unit of Measure')

    # Pricing
    default_price = models.DecimalField(decimal_places=2, max_digits=12)
    product_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # optional
    profit_margin = models.DecimalField(max_digits=5, default=0, decimal_places=2, null=True, blank=True)
    max_discount_percent = models.DecimalField(decimal_places=2, max_digits=5, default=0)

    # Accounting
    revenue_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True,
        related_name='products_revenue', help_text='Income account for sales of this product')
    cogs_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True,
        related_name='products_cogs', help_text='Cost of goods sold account for this product')
    expense_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='products_expense')

    costing_method = models.CharField(max_length=20, choices=COSTING_METHODS, default='average')
    inventory_valuation = models.CharField(max_length=20, choices=VALUATION_METHODS, default='automated')
    purchase_method = models.CharField(max_length=20, choices=PURCHASE_METHOD, default='receive',
                                       help_text='Control policy for vendor bills')
    sales_invoicing_method = models.CharField(max_length=20, choices=INVOICING_METHOD_CHOICES, default='order')
    return_invoicing_method = models.CharField(max_length=20, choices=REFUND_METHOD_CHOICES, default='receiving')

    # timestamp
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # tax
    sales_taxes = models.ManyToManyField('accounting.Tax', blank=True, related_name='products_sales')
    purchase_taxes = models.ManyToManyField('accounting.Tax', blank=True, related_name='products_purchase')

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('name'), name='unique_product_name_ci'),
            models.UniqueConstraint(fields=['barcode', 'company'], condition=Q(barcode__isnull=False),
                                    name='product_barcode_company_uniq'),
        ]

    # -- stockability -------------------------------------------------------- #
    @property
    def is_stockable(self):
        """Only storable/consumable products can appear in a StockMove; a
        service is never received, moved, or sat in a location."""
        return self.product_type in ('storable', 'consumable')

    def _validate(self):
        if self.uom_po_id and self.uom_id and self.uom_po.category_id != self.uom.category_id:
            raise ValidationError(
                'The purchase Unit of Measure must be the same dimension as the storage Unit of Measure '
                f'({self.uom.category} vs {self.uom_po.category}).')
        if self.tracking == self.Tracking.SERIAL and self.uom_id and self.uom.rounding != Decimal('1'):
            raise ValidationError('A serial-tracked product needs a whole-unit storage Unit of Measure '
                                  '(rounding = 1), since a serial number cannot be a fraction of a unit.')
        if self.tracking != self.Tracking.NONE and not self.is_stockable:
            raise ValidationError(f'A {self.get_product_type_display()} product cannot be lot/serial tracked.')
        if self.is_stockable and not self.uom_id:
            raise ValidationError('A storable or consumable product needs a storage Unit of Measure.')

    def clean(self):
        super().clean()
        self._validate()

    def save(self, *args, **kwargs):
        if not self.uom_po_id:
            self.uom_po_id = self.uom_id

        if self.default_price and self.default_price > 0:
            # Margin % = ((Price - Cost) / Price) * 100
            self.profit_margin = ((self.default_price - self.product_cost) / self.default_price) * 100
        else:
            self.profit_margin = 0.00

        self._validate()
        super().save(*args, **kwargs)

    # -- stock ---------------------------------------------------------------- #
    def available_stock(self):
        from inventory.models import StockQuant
        total_quantity = (
            StockQuant.objects
            .filter(product=self)
            .aggregate(total=Coalesce(Sum('quantity'), 0, output_field=models.DecimalField()))['total']
        )
        return total_quantity

    def reserved_stock(self):
        from inventory.models import StockLocation
        """Stock already committed to an outgoing move that hasn't completed yet.
        Only counts moves *leaving* a stockable location (sales, returns to
        supplier, internal reservations) -- a pending *receipt* increases what's
        coming in, it doesn't commit anything that's already on the shelf, so it
        must not reduce `available_to_sale`."""
        from inventory.models import StockMove
        total_reserved = StockMove.objects.filter(
            product=self, status__in=StockMove.ACTIVE_STATUSES,
            source_location__usage=StockLocation.Usage.INTERNAL,
        ).aggregate(total=Coalesce(Sum('quantity'), 0, output_field=models.DecimalField()))['total']
        return total_reserved

    @property
    def available_to_sale(self):
        return self.available_stock() - self.reserved_stock()

    # -- pricing ---------------------------------------------------------------- #
    def minimum_price(self):
        if self.product_cost and self.profit_margin:
            return self.product_cost * (Decimal('1') + self.profit_margin / Decimal('100'))
        return None

    def get_current_price(self):
        today = timezone.now()
        price_obj = (self.prices.filter(start_date__lte=today, end_date__gte=today)
                     .order_by('-start_date').first())
        return price_obj.price if price_obj else self.default_price

    def get_valuation_method(self):
        return self.inventory_valuation

    def get_costing_method(self):
        return self.costing_method

    def __str__(self):
        return self.name


class ProductPrice(models.Model):
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='prices')
    price = models.DecimalField(decimal_places=2, max_digits=12)
    product_cost = models.DecimalField(decimal_places=2, max_digits=12)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        unique_together = ('product', 'start_date')
        verbose_name = 'Product Price'
        verbose_name_plural = 'Product Prices'

    def clean(self):
        super().clean()
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError('End date cannot be before start date.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.product.name} - {self.price} from {self.start_date}'


class ProductPackaging(models.Model):
    """A convenience/scanning layer on top of Product + UoM (Odoo: product.packaging).
    Maps one barcode (e.g. a case or box) to a fixed quantity of the product,
    expressed in the product's storage UoM. Scanning it should only look up
    that quantity for an order/move line -- it never changes how stock itself
    is counted or valued; the quant still moves in `product.uom`.
    """
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='packagings')
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='product_packagings',
                                editable=False)
    name = models.CharField(max_length=100, help_text="e.g. 'Box of 24', 'Pallet'")
    qty = models.DecimalField(max_digits=14, decimal_places=6, help_text="Quantity, in the product's storage UoM")
    barcode = models.CharField(max_length=64, null=True, blank=True)
    sequence = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['product_id', 'sequence']
        constraints = [
            models.UniqueConstraint(fields=['barcode', 'company'], condition=Q(barcode__isnull=False),
                                    name='packaging_barcode_company_uniq'),
        ]

    def __str__(self):
        return f'{self.product.name} - {self.name}'

    def clean(self):
        super().clean()
        if self.qty is not None and self.qty <= 0:
            raise ValidationError('Packaging quantity must be greater than zero.')

    def save(self, *args, **kwargs):
        self.company_id = self.product.company_id
        self.full_clean(exclude=[f.name for f in self._meta.fields if f.name not in ('qty',)])
        super().save(*args, **kwargs)

    def resolve(self):
        """What scanning this barcode should populate on an order/move line:
        the product, the quantity this package represents, and the UoM it's in."""
        return {'product': self.product, 'qty': self.qty, 'uom': self.product.uom}


def resolve_barcode(code, company=None):
    from inventory.models import StockLot, StockLocation
    """Best-effort scan resolver: tries each barcode-bearing model in the order
    a picker's scan is most likely to mean it, and returns (kind, object) or
    (None, None). Callers that already know what they expect (e.g. "scan a
    location now") should query that model directly instead of this generic
    fallback -- context resolves ambiguity far better than a global lookup.
    """
    if not code:
        return None, None
    scoped = lambda qs: qs.filter(company=company) if company else qs

    obj = scoped(Product.objects.filter(barcode=code, active=True)).first()
    if obj:
        return 'product', obj

    obj = scoped(ProductPackaging.objects.filter(barcode=code, active=True)).first()
    if obj:
        return 'packaging', obj

    obj = scoped(StockLocation.objects.filter(barcode=code, active=True)).first()
    if obj:
        return 'location', obj

    # Lot "barcodes" are just the lot name; a bare name is ambiguous across
    # products (the unique key is product+name+company), so this is a
    # last-resort, first-match guess -- prefer looking lots up once the
    # product is already known from an earlier scan in the same session.
    obj = scoped(StockLot.objects.filter(name=code)).first()
    if obj:
        return 'lot', obj

    return None, None