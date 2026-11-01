from django.db import models


class FiscalYear(models.Model):
    """
    Explicit fiscal year record — only needed when a company's fiscal year
    doesn't follow the standard recurring rule (Company.fiscal_year_start_month/day).
    Most companies never create any of these; boundaries are computed on the fly
    via Company.get_fiscal_year_dates() instead.
    """
    company = models.ForeignKey(
        'core.Company', on_delete=models.CASCADE, related_name='fiscal_years'
    )
    name = models.CharField(max_length=50)          # e.g. "FY2025", "Stub Q1 2025"
    date_from = models.DateField()
    date_to = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_fiscal_year_name_per_company'),
            models.CheckConstraint(condition=models.Q(date_to__gte=models.F('date_from')), name='fy_dates_valid'),
        ]
        ordering = ['-date_from']

    def __str__(self):
        return f"{self.name} ({self.date_from} – {self.date_to})"

    def clean(self):
        from django.core.exceptions import ValidationError
        overlapping = FiscalYear.objects.filter(
            company=self.company,
            date_from__lte=self.date_to,
            date_to__gte=self.date_from,
        ).exclude(pk=self.pk)
        if overlapping.exists():
            raise ValidationError("Fiscal year dates overlap with an existing fiscal year for this company.")