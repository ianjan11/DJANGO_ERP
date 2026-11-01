from decimal import Decimal
from django.db import models
from django.db.models import Q
from django.utils import timezone

class StockLot(models.Model):
    """Lot / batch number (Odoo: stock.lot). One row per product + lot name + company."""
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='lots')
    name = models.CharField(max_length=100, help_text='Batch/Lot number')
    company = models.ForeignKey('core.Company', on_delete=models.PROTECT, related_name='stock_lots')

    # Traceability
    supplier = models.ForeignKey('core.Partner', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='supplied_lots')
    supplier_lot_number = models.CharField(max_length=100, null=True, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'name', 'company'], name='unique_product_lot'),
            # Django < 5.1: use `check=` instead of `condition=`.
            models.CheckConstraint(
                condition=(Q(expiration_date__isnull=True) | Q(manufacture_date__isnull=True)
                           | Q(expiration_date__gte=models.F('manufacture_date'))),
                name='stock_lot_expiry_after_manufacture'),
        ]

    def __str__(self):
        return f'{self.product.name} - {self.name}'

    @property
    def is_expired(self):
        return bool(self.expiration_date and self.expiration_date < timezone.localdate())

    @property
    def on_hand(self):
        from inventory.models import StockLocation
        """Odoo's lot.product_qty: total in internal locations."""
        total = self.quants.filter(location__usage=StockLocation.Usage.INTERNAL) \
                           .aggregate(t=models.Sum('quantity'))['t']
        return total or Decimal('0')

    # StockLot
    @classmethod
    def get_or_create_for(cls, product, name, company_id, **extra):
        name = name.strip().upper()  # one normalisation point
        lot, _ = cls.objects.get_or_create(
            product=product, name=name, company_id=company_id, defaults=extra)
        return lot






