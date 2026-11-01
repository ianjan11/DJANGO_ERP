from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

class Company(models.Model):
    code = models.CharField(max_length=20, unique=True)

    name = models.CharField(max_length=200)

    partner = models.OneToOneField(
        'core.Partner', on_delete=models.CASCADE, related_name='company_profile'
    )  # this Partner row IS the company's identity — name, address, VAT all live there

    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='children'
    )

    country = models.ForeignKey(
        'core.Country', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='companies',
    )
    currency = models.ForeignKey('core.Currency', on_delete=models.PROTECT, related_name='companies')

    chart_key = models.CharField(
        max_length=50, blank=True,
        help_text="Identifies which l10n/ XML bundle was used to provision this "
                  "company's books, e.g. 'us', 'in'. Not a FK — no DB-persisted "
                  "template layer exists anymore."
    )

    fiscal_year_start_month = models.PositiveSmallIntegerField(default=1)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)
    lock_date = models.DateField(null=True, blank=True)
    tax_lock_date = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Companies'

    # --- proxies onto partner ---
    @property
    def vat(self):
        return self.partner.tax_id

    def __str__(self):
        return self.name

    def get_settings_dict(self):
        settings = self.account_settings.select_related('account').all()
        return {s.key: s.account for s in settings}

    @classmethod
    def create_company(cls, *, code, name, currency, country=None, **extra):
        """
        Odoo overrides res.company.create() to auto-create the backing partner.
        We replicate that explicitly here rather than overriding .objects.create(),
        since Django doesn't let a model easily create a *different* model as a
        side effect of its own manager without this kind of wrapper.
        """
        from django.db import transaction
        from core.models import Partner

        with transaction.atomic():
            partner = Partner.objects.create(
                name=name, is_company=True, country=country
            )
            company = cls.objects.create(
                code=code, partner=partner, currency=currency,
                country=country, **extra
            )
            # now that the company exists, scope its own partner record to itself
            partner.company = company
            partner.save(update_fields=['company'])
            return company

    def get_fiscal_year_dates(self, reference_date):
        """Return (date_from, date_to) of the fiscal year containing reference_date."""
        import calendar
        from datetime import date, timedelta

        month, day = self.fiscal_year_start_month, self.fiscal_year_start_day
        max_day = calendar.monthrange(reference_date.year, month)[1]
        start_this_year = date(reference_date.year, month, min(day, max_day))

        if reference_date >= start_this_year:
            date_from = start_this_year
            next_year = reference_date.year + 1
        else:
            prev_max_day = calendar.monthrange(reference_date.year - 1, month)[1]
            date_from = date(reference_date.year - 1, month, min(day, prev_max_day))
            next_year = reference_date.year

        next_max_day = calendar.monthrange(next_year, month)[1]
        date_to = date(next_year, month, min(day, next_max_day)) - timedelta(days=1)
        return date_from, date_to








