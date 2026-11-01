from django.db import models
from decimal import Decimal

class StockValuationLayer(models.Model):

    SOURCE_TYPES = (
        ("RECEIPT", "Receipt"),
        ("DELIVERY", "Delivery"),
        ("CUSTOMER_RETURN", "Customer Return"),
        ("SUPPLIER_RETURN", "Supplier Return"),
        ("ADJUSTMENT", "Inventory Adjustment"),
        ("REVALUATION", "Inventory Revaluation"),
    )

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="valuation_layers"
    )

    company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="valuation_layers"
    )

    lot = models.ForeignKey(
        "inventory.StockLot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="valuation_layers"
    )

    # Quantity entering/leaving valuation
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    # Quantity still available for FIFO consumption
    remaining_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0")
    )


    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=4
    )


    value = models.DecimalField(
        max_digits=16,
        decimal_places=2
    )


    source_type = models.CharField(
        max_length=30,
        choices=SOURCE_TYPES
    )


    source_id = models.PositiveIntegerField(
        help_text="ID of receipt, delivery, adjustment, etc."
    )


    created_at = models.DateTimeField(
        auto_now_add=True
    )


    class Meta:
        ordering = [
            "created_at"
        ]

    def save(self, *args, **kwargs):
        if not self.value:
            self.value = self.quantity * self.unit_cost

        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity

        super().save(*args, **kwargs)


    def __str__(self):
        return (
            f"{self.product.name} "
            f"{self.quantity} @ {self.unit_cost}"
        )