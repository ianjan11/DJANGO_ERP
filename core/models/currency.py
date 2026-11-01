from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models


# ---------------------------
# Currency
# ---------------------------
class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)   # e.g. USD, EUR, TZS
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=5)
    is_active = models.BooleanField(default=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)


    def __str__(self):
        return f"{self.code} - {self.name}"

    def quantum(self):
        """Return the Decimal quantize target for this currency's precision."""
        return Decimal("1").scaleb(-self.decimal_places)



class CompanyCurrency(models.Model):
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, null=True, blank=True)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT, related_name='company_currency')

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "currency"],
                name="unique_company_currency",
            )
        ]

    def __str__(self):
        return f"{self.currency.code} - {self.currency.name}"



class ExchangeRate(models.Model):

    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT, related_name='rates_from')
    rate = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("0.000001")),
        ],
    )
    date = models.DateField()
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('currency', 'date', 'company')
        indexes = [models.Index(fields=["company", "currency", "-date"])]




