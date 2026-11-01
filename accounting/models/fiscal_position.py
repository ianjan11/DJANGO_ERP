from django.db import models


class FiscalPosition(models.Model):
    company = models.ForeignKey(
        'core.Company', on_delete=models.CASCADE, related_name='fiscal_positions'
    )
    name = models.CharField(max_length=100)

    country = models.ForeignKey(
        'core.Country', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )
    country_group = models.ForeignKey(
        'core.CountryGroup', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )

    auto_apply = models.BooleanField(
        default=False,
        help_text="If set, Odoo-style auto-matching applies this position "
                   "based on the customer/vendor's country, without manual selection."
    )
    vat_required = models.BooleanField(
        default=False,
        help_text="Only auto-apply if the partner has a tax_id set (e.g. EU B2B reverse charge)."
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_fiscal_position_name_per_company')
        ]
        ordering = ['name']

    def __str__(self):
        return self.name

    def map_tax(self, tax):
        """Return the substituted tax for a given source tax, or the original if no mapping exists."""
        mapping = self.tax_mappings.filter(tax_src=tax).first()
        if mapping:
            return mapping.tax_dest          # may be None -> means "remove this tax"
        return tax

    def map_account(self, account):
        """Return the substituted account for a given source account, or the original."""
        mapping = self.account_mappings.filter(account_src=account).first()
        return mapping.account_dest if mapping else account

    @classmethod
    def get_auto_apply_position(cls, company, partner):
        """
        Mirrors Odoo's _get_fiscal_position(): find the best-matching
        auto_apply position for a given partner, or None.
        """
        qs = cls.objects.filter(company=company, auto_apply=True, is_active=True)

        if partner.tax_id:
            qs_vat = qs.filter(vat_required=True)
        else:
            qs_vat = qs.exclude(vat_required=True)

        # country match takes priority over country_group match
        if partner.country_id:
            position = qs_vat.filter(country_id=partner.country_id).first()
            if position:
                return position
            position = qs_vat.filter(country_group__countries=partner.country_id).first()
            if position:
                return position

        # fallback: a position with no country/group set at all = catch-all
        return qs_vat.filter(country__isnull=True, country_group__isnull=True).first()


class FiscalPositionTaxMapping(models.Model):
    """account.fiscal.position.tax equivalent — tax substitution rules."""
    fiscal_position = models.ForeignKey(
        FiscalPosition, on_delete=models.CASCADE, related_name='tax_mappings'
    )
    tax_src = models.ForeignKey(
        'accounting.Tax', on_delete=models.CASCADE, related_name='+',
        help_text="The tax normally applied on the product/line."
    )
    tax_dest = models.ForeignKey(
        'accounting.Tax', null=True, blank=True,
        on_delete=models.CASCADE, related_name='+',
        help_text="The tax to use instead. NULL means 'remove the tax entirely' "
                   "(e.g. export sales, reverse charge)."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fiscal_position', 'tax_src'], name='unique_tax_mapping_per_position'
            )
        ]

    def __str__(self):
        dest = self.tax_dest.name if self.tax_dest else "(removed)"
        return f"{self.tax_src.name} -> {dest}"


class FiscalPositionAccountMapping(models.Model):
    """account.fiscal.position.account equivalent — GL account substitution rules."""
    fiscal_position = models.ForeignKey(
        FiscalPosition, on_delete=models.CASCADE, related_name='account_mappings'
    )
    account_src = models.ForeignKey(
        'accounting.Account', on_delete=models.CASCADE, related_name='+'
    )
    account_dest = models.ForeignKey(
        'accounting.Account', on_delete=models.CASCADE, related_name='+'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fiscal_position', 'account_src'], name='unique_account_mapping_per_position'
            )
        ]

    def __str__(self):
        return f"{self.account_src.code} -> {self.account_dest.code}"