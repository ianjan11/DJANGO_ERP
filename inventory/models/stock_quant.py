from decimal import Decimal
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum



class StockQuant(models.Model):
    """Quantity of a product (optionally of one lot) sitting in one location. Only internal/transit
    locations have quants; vendor/customer/inventory/production are virtual."""
    ALLOW_NEGATIVE_STOCK = True     # Odoo allows negatives by default; flip if you want that

    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='quants')
    location = models.ForeignKey('inventory.StockLocation', on_delete=models.PROTECT, related_name='quants')
    lot = models.ForeignKey('inventory.StockLot', null=True, blank=True, on_delete=models.PROTECT, related_name='quants')
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='quants')
    in_date = models.DateTimeField(null=True, blank=True, editable=False)


    # Odoo: stock.quant.package_id. Null = loose stock. A package is a physical instance
    # (a specific bag/pallet); its type, if any, lives on package.packaging.
    package = models.ForeignKey('inventory.StockQuantPackage', null=True, blank=True,
                                on_delete=models.PROTECT, related_name='quants')
    # Odoo: reserved_quantity. Stock promised to pending moves; free = quantity - reserved_quantity.
    reserved_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        constraints = [
            # nulls_distinct=False makes "no lot" / "no package" compare equal (PostgreSQL 15+, Django 5.0+).
            models.UniqueConstraint(fields=['product', 'location', 'lot', 'package'], nulls_distinct=False,
                                    name='stock_quant_product_location_lot_package_uniq'),
            models.CheckConstraint(condition=Q(reserved_quantity__gte=0), name='stock_quant_reserved_gte_0'),
        ]

    def __str__(self):
        lot = f' [{self.lot.name}]' if self.lot_id else ''
        return f'{self.product}{lot} @ {self.location}: {self.quantity}'


    @classmethod
    def apply(cls, product_id, location, delta, lot=None, package=None):
        """Add `delta` (may be negative) to the quant. Call inside a transaction."""
        from inventory.models import Product

        if not location.is_stockable:
            raise ValidationError(f'"{location.complete_name}" cannot hold stock (type: {location.usage}).')
        product = Product.objects.get(pk=product_id)
        if not product.is_stockable:
            raise ValidationError(f'{product.name} is a {product.get_product_type_display()}; '
                                  'it cannot be held in stock.')
        if not location.company_id:
            raise ValidationError(f'"{location.complete_name}" has no company; cannot create a quant for it.')
        if package and package.company_id != location.company_id:
            raise ValidationError(f'Package "{package}" belongs to another company than "{location.complete_name}".')

        quant, _ = cls.objects.get_or_create(
            product_id=product_id,
            location=location,
            lot=lot,
            package=package,
            defaults={'company_id': location.company_id, 'in_date': timezone.now()},
        )
        quant = cls.objects.select_for_update().get(pk=quant.pk)
        new_qty = quant.quantity + delta
        if new_qty < 0 and not cls.ALLOW_NEGATIVE_STOCK:
            raise ValidationError(
                f'Not enough stock in "{location.complete_name}"'
                f'{f" for lot {lot.name}" if lot else ""}: have {quant.quantity}, need {-delta}.')
        quant.quantity = new_qty
        quant.save(update_fields=['quantity'])

    @classmethod
    def release(cls, product_id, location, qty, lot=None, package=None):
        """Give back `qty` of reservation on the matching quant. Call inside a transaction."""
        quant = cls.objects.select_for_update().filter(
            product_id=product_id, location=location, lot=lot, package=package).first()
        if quant:
            quant.reserved_quantity = max(Decimal('0'), quant.reserved_quantity - qty)
            quant.save(update_fields=['reserved_quantity'])






class StockQuantPackage(models.Model):
    """A physical container instance: one specific bag, carton or pallet (Odoo: stock.quant.package).

    Contents are the quants that point at it (quant.package). Its location is derived from those
    quants, never stored, so it cannot drift. `packaging` is the optional *type* ("Bag 25 kg"),
    which is what lets allocation tell a sealed bag from an opened one.
    """
    name = models.CharField(max_length=100, blank=True, help_text='Scanned ID. Auto-generated if blank.')
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='quant_packages')
    packaging = models.ForeignKey('inventory.ProductPackaging', null=True, blank=True,
                                  on_delete=models.PROTECT, related_name='packages')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'company'], condition=~Q(name=''),
                                    name='quant_package_name_company_uniq'),
        ]

    def __str__(self):
        return self.name or f'Package #{self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.name:
            self.name = f'PACK{self.pk:07d}'
            type(self).objects.filter(pk=self.pk).update(name=self.name)

    @property
    def stocked_quants(self):
        return self.quants.exclude(quantity=0)

    @property
    def location(self):
        """The one location holding this package, or None if it is empty or inconsistent."""
        locs = {q.location for q in self.stocked_quants.select_related('location')}
        return next(iter(locs)) if len(locs) == 1 else None

    def assert_single_location(self):
        if self.stocked_quants.values('location_id').distinct().count() > 1:
            raise ValidationError(f'Package "{self}" would be split across several locations.')

    @property
    def is_sealed(self):
        """True if contents equal the packaging type's quantity. None if the package has no type."""
        if not self.packaging_id:
            return None
        total = self.stocked_quants.aggregate(t=Sum('quantity'))['t'] or 0
        return total == self.packaging.qty

    @transaction.atomic
    def unpack(self):
        """Open the package: its contents become loose stock in the same location (Odoo: unpack).
        Like Odoo, this changes quants directly and creates no stock move."""
        from inventory.models import StockQuant
        quants = list(self.quants.select_for_update().exclude(quantity=0))
        if any(q.reserved_quantity for q in quants):
            raise ValidationError(f'Package "{self}" is reserved by a pending move; unreserve it first.')
        for q in quants:
            StockQuant.apply(q.product_id, q.location, -q.quantity, lot=q.lot, package=self)
            StockQuant.apply(q.product_id, q.location, q.quantity, lot=q.lot)