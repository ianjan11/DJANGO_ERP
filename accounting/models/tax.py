from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class TaxGroup(models.Model):
    """Reporting bucket for taxes (e.g. VAT, Withholding Tax).
    Not to be confused with a Tax whose computation is 'GROUP'."""
    name = models.CharField(max_length=100)
    sequence = models.IntegerField(default=10)

    class Meta:
        ordering = ['sequence', 'id']

    def __str__(self):
        return self.name


class Tax(models.Model):
    """
    A tax as consumed by core.services.tax_engine.TaxCalculatorService.

    Two kinds of rows:
      * LEAF taxes  (computation PERCENT / FIXED): carry a rate and an account.
      * GROUP taxes (computation GROUP): carry NO rate and NO account of their
        own. They are just an ordered bundle of children (children point at them
        through `parent_tax`). The engine replaces a group by its active
        children, so posting, reporting and cost logic only ever see leaves.

    A group's `price_include` / `include_base_amount` flags are inherited by its
    children (OR-ed with the child's own flags).
    """
    class TypeTaxUse(models.TextChoices):
        SALE = 'SALE', 'Sales'
        PURCHASE = 'PURCHASE', 'Purchase'
        NONE = 'NONE', 'None'

    class Computation(models.TextChoices):
        PERCENT = 'PERCENT', 'Percentage of price'
        FIXED = 'FIXED', 'Fixed amount (per unit)'
        GROUP = 'GROUP', 'Group of taxes'

    MAX_GROUP_DEPTH = 5   # keep in sync with TaxCalculatorService.MAX_GROUP_DEPTH

    name = models.CharField(max_length=100)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='taxes')
    is_active = models.BooleanField(default=True)

    type_tax_use = models.CharField(max_length=20, choices=TypeTaxUse.choices, default=TypeTaxUse.SALE)
    computation = models.CharField(max_length=20, choices=Computation.choices, default=Computation.PERCENT)
    rate = models.DecimalField(max_digits=12, decimal_places=5, default=Decimal('0'),
                               help_text='Percent for PERCENT taxes, amount per unit for FIXED. Ignored for GROUP.')
    sequence = models.IntegerField(default=10, help_text='Lower sequence runs first (also orders children in a group)')

    # --- engine behaviour --------------------------------------------------- #
    price_include = models.BooleanField(
        default=False, help_text='The price already includes this tax (the engine unwinds it to find the base).')
    include_base_amount = models.BooleanField(
        default=False, help_text='Compound: later taxes are computed on base + this tax.')

    # --- purchase cost behaviour -------------------------------------------- #
    is_recoverable = models.BooleanField(
        default=True,
        help_text='Uncheck for purchase taxes that cannot be reclaimed (import duty, non-deductible VAT). '
                  'They are capitalised into inventory cost instead of going to the tax account.')

    # --- structure ------------------------------------------------------------ #
    parent_tax = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='children',
                                   limit_choices_to={'computation': 'GROUP'},
                                   help_text='The GROUP tax this tax belongs to.')

    # --- accounting ------------------------------------------------------------- #
    account = models.ForeignKey('accounting.Account', on_delete=models.PROTECT, null=True, blank=True,
                                related_name='+',
                                help_text='Tax liability/asset account (collected tax). Required for non-group taxes.')
    account_refund = models.ForeignKey('accounting.Account', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='+', help_text='Account used on refunds/credit notes')
    tax_group = models.ForeignKey(TaxGroup, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ['sequence', 'id']
        indexes = [models.Index(fields=['company', 'type_tax_use', 'is_active'])]

    # ------------------------------------------------------------------ #
    # Display
    # ------------------------------------------------------------------ #
    def __str__(self):
        if self.is_group:
            return f'{self.name} (group)'
        suffix = f'{self.rate:.2f}' + ('%' if self.computation == self.Computation.PERCENT else '')
        return f'{self.name}-{suffix}'

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @property
    def is_group(self):
        return self.computation == self.Computation.GROUP

    @property
    def is_capitalised_in_cost(self):
        """True when this (leaf) purchase tax is part of the cost of the goods."""
        return (not self.is_group and not self.is_recoverable
                and self.type_tax_use in (self.TypeTaxUse.PURCHASE, self.TypeTaxUse.NONE))

    def leaf_taxes(self):
        """The concrete taxes this tax resolves to (itself, or its active children recursively)."""
        from core.services.tax_engine import TaxCalculatorService
        return [e.tax for e in TaxCalculatorService.flatten_taxes([self])]

    def get_account(self, is_refund=False):
        """Account to post this (leaf) tax to; refunds fall back to the normal account."""
        if self.is_group:
            raise ValueError(f"Tax group '{self.name}' has no account; post its children instead.")
        return self.account_refund if is_refund and self.account_refund_id else self.account

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def clean(self):
        super().clean()
        errors = {}

        if self.is_group:
            if self.account_id or self.account_refund_id:
                errors['account'] = 'A tax group has no account of its own; set accounts on its child taxes.'
            if self.rate:
                errors['rate'] = 'A tax group has no rate; its children carry the rates.'
        else:
            if not self.account_id:
                errors['account'] = 'A tax needs an account (only GROUP taxes may leave it empty).'
            if self.rate is not None and self.rate < 0:
                errors['rate'] = 'Rate cannot be negative.'
            if self.pk and self.children.exists():
                errors['computation'] = 'A tax that has child taxes must use the GROUP computation.'

        if not self.is_recoverable and self.type_tax_use == self.TypeTaxUse.SALE:
            errors['is_recoverable'] = ('"Recoverable" only describes purchase taxes; '
                                        'a sales tax is always collected, never capitalised.')

        if self.parent_tax_id:
            parent = self.parent_tax
            if not parent.is_group:
                errors['parent_tax'] = 'The parent must be a GROUP tax.'
            elif parent.company_id != self.company_id:
                errors['parent_tax'] = 'The parent tax belongs to a different company.'
            elif (self.TypeTaxUse.NONE not in (self.type_tax_use, parent.type_tax_use)
                  and self.type_tax_use != parent.type_tax_use):
                errors['parent_tax'] = (f'A {self.type_tax_use} tax cannot sit in a '
                                        f'{parent.type_tax_use} group.')
            else:
                self._check_group_chain(errors)

        if errors:
            raise ValidationError(errors)

    def _check_group_chain(self, errors):
        """Reject cycles and nesting deeper than the engine supports."""
        depth, node = 0, self.parent_tax
        while node is not None:
            depth += 1
            if (self.pk and node.pk == self.pk) or depth > self.MAX_GROUP_DEPTH:
                errors['parent_tax'] = 'Circular or too deeply nested tax group.'
                return
            node = node.parent_tax

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class TaxLine(models.Model):
    """Per-leaf-tax breakdown of a journal line (what the engine returns in result['lines'])."""
    tax = models.ForeignKey(Tax, on_delete=models.CASCADE)
    move_line = models.ForeignKey('accounting.AccountMoveLine', on_delete=models.CASCADE)
    base_amount = models.DecimalField(max_digits=15, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2)
    source_line = models.ForeignKey('accounting.AccountMoveLine', on_delete=models.CASCADE,
                                    null=True, blank=True, related_name='sourced_tax_lines',
                                    help_text='The base line that generated this tax line')

    def __str__(self):
        return f'{self.tax.name}: {self.tax_amount}'

    def clean(self):
        super().clean()
        if self.tax_id and self.tax.is_group:
            raise ValidationError({'tax': 'A tax line must reference a concrete tax, not a group '
                                          '(the engine already expands groups into their children).'})