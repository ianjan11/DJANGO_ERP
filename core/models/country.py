from django.db import models

class Country(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=2, unique=True)        # ISO 3166-1 alpha-2, e.g. "US"
    code_alpha3 = models.CharField(max_length=3, blank=True)

    currency = models.ForeignKey(
        'core.Currency', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='countries'
    )

    phone_code = models.PositiveIntegerField(null=True, blank=True)

    address_format = models.TextField(
        blank=True,
        help_text="Template string for rendering addresses, e.g. "
                   "'%(street)s\\n%(city)s, %(state)s %(zip)s\\n%(country)s'"
    )

    zip_required = models.BooleanField(default=True)
    state_required = models.BooleanField(default=False)
    vat_label = models.CharField(
        max_length=50, blank=True,
        help_text="Localized label for tax ID, e.g. 'SIRET', 'GSTIN', 'EIN'"
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Countries'

    def __str__(self):
        return self.name


class CountryState(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='states')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['country', 'code'], name='unique_state_code_per_country')
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.country.code})"


class CountryGroup(models.Model):
    """Used for fiscal-position auto-apply logic scoped to a region, e.g. 'EU'."""
    name = models.CharField(max_length=100)
    countries = models.ManyToManyField(Country, related_name='groups', blank=True)

    def __str__(self):
        return self.name

