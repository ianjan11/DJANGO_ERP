from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import models

# --------------------------------------------------------------------------- #
# Units of measure (uom.category / uom.uom)
# --------------------------------------------------------------------------- #
class UomCategory(models.Model):
    """A dimension: Weight, Volume, Unit, Length, Time... UoMs only convert
    within their own category. Each category has exactly one 'reference' UoM
    (factor = 1); every other UoM's factor is relative to it."""
    name = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.name


class Uom(models.Model):
    class Type(models.TextChoices):
        REFERENCE = 'reference', 'Reference Unit of Measure for this category'
        BIGGER = 'bigger', 'Bigger than the reference Unit of Measure'
        SMALLER = 'smaller', 'Smaller than the reference Unit of Measure'

    name = models.CharField(max_length=64)
    category = models.ForeignKey(UomCategory, on_delete=models.PROTECT, related_name='uoms')
    uom_type = models.CharField(max_length=10, choices=Type.choices, default=Type.REFERENCE)
    # 1 (reference unit) = factor * (this unit). E.g. category "Weight", reference "kg":
    #   kg:    factor = 1        (reference)
    #   g:     factor = 1000     (1 kg = 1000 g            -> smaller, factor > 1)
    #   ton:   factor = 0.001    (1 kg = 0.001 t            -> bigger,   factor < 1)
    factor = models.DecimalField(max_digits=16, decimal_places=8, default=Decimal('1'))
    # Smallest countable increment in this unit: 1 for "Units"/serials, 0.01 for kg, etc.
    rounding = models.DecimalField(max_digits=24, decimal_places=12, default=Decimal('0.01'))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category_id', 'factor']
        constraints = [
            models.UniqueConstraint(fields=['category', 'name'], name='uom_category_name_uniq'),
        ]

    def __str__(self):
        return self.name

    def _validate(self):
        if self.factor <= 0:
            raise ValidationError('The conversion factor must be greater than zero.')
        if self.rounding <= 0:
            raise ValidationError('The rounding precision must be greater than zero.')
        if self.uom_type == self.Type.REFERENCE and self.factor != 1:
            raise ValidationError('The reference Unit of Measure for a category must have a factor of 1.')
        if self.uom_type == self.Type.BIGGER and not (0 < self.factor < 1):
            raise ValidationError('A "bigger" Unit of Measure must have a factor below 1.')
        if self.uom_type == self.Type.SMALLER and self.factor <= 1:
            raise ValidationError('A "smaller" Unit of Measure must have a factor above 1.')
        if self.uom_type == self.Type.REFERENCE:
            other_ref = Uom.objects.filter(
                category_id=self.category_id, uom_type=self.Type.REFERENCE, active=True).exclude(pk=self.pk)
            if other_ref.exists():
                raise ValidationError(
                    f'Category "{self.category}" already has a reference Unit of Measure.')

    def clean(self):
        super().clean()
        self._validate()

    def save(self, *args, **kwargs):
        self._validate()
        super().save(*args, **kwargs)

    def convert_to(self, qty, target_uom):
        """Convert qty from self to target_uom without applying quantity rounding."""
        if target_uom.category_id != self.category_id:
            raise ValidationError(
                f'Cannot convert between "{self}" ({self.category}) and '
                f'"{target_uom}" ({target_uom.category}).'
            )

        if target_uom.pk == self.pk:
            return Decimal(qty)

        reference_qty = Decimal(qty) / self.factor
        return reference_qty * target_uom.factor
