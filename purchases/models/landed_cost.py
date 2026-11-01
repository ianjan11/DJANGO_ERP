from django.db import models

class LandedCostMethod(models.TextChoices):

    BY_VALUE = (
        "value",
        "By Purchase Value"
    )

    BY_QUANTITY = (
        "quantity",
        "By Quantity"
    )

    BY_WEIGHT = (
        "weight",
        "By Weight"
    )

    BY_VOLUME = (
        "volume",
        "By Volume"
    )



class LandedCost(models.Model):

    company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="landed_costs"
    )

    name = models.CharField(
        max_length=100,
        unique=True
    )

    date = models.DateField()

    state = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft"
    )

    allocation_method = models.CharField(
        max_length=20,
        choices=LandedCostMethod.choices,
        default="value"
    )

    currency = models.ForeignKey(
        "accounting.Currency",
        on_delete=models.PROTECT
    )

    journal = models.ForeignKey(
        "accounting.Journal",
        on_delete=models.PROTECT
    )

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.name



class LandedCostLine(models.Model):

    landed_cost = models.ForeignKey(
        LandedCost,
        related_name="lines",
        on_delete=models.CASCADE
    )

    account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        help_text="Expense account being capitalized"
    )

    description = models.CharField(
        max_length=255
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    def __str__(self):
        return self.description




class LandedCostReceipt(models.Model):

    landed_cost = models.ForeignKey(
        LandedCost,
        related_name="receipts",
        on_delete=models.CASCADE
    )


    class Meta:
        unique_together = (
            "landed_cost",
        )




class LandedCostAllocations(models.Model):

    landed_cost = models.ForeignKey(
        LandedCost,
        related_name="allocations",
        on_delete=models.CASCADE
    )

    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT
    )

    lot = models.ForeignKey(
        "inventory.StockLot",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )

    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    additional_value = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )
