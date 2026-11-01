from django.db import models


class Partner(models.Model):
    PARTNER_TYPES = [
        ('CUSTOMER', 'Customer'),
        ('VENDOR', 'Vendor'),
        ('BOTH', 'Both'),
    ]

    name = models.CharField(max_length=200)
    is_company = models.BooleanField(default=False)
    partner_type = models.CharField(
        max_length=20, choices=PARTNER_TYPES, default='CUSTOMER', blank=True
    )  # meaningless when this partner IS a Company's own identity — leave default

    # sub-contacts, e.g. "Jane Doe" under "Acme Corp"
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='contacts'
    )

    # which company's books this partner is SCOPED to. NULL = shared/global,
    # visible from any company (mirrors Odoo: company_id nullable on res.partner)
    company = models.ForeignKey(
        'core.Company', null=True, blank=True,
        on_delete=models.CASCADE, related_name='partners'
    )

    tax_id = models.CharField(max_length=50, blank=True, null=True, default=None)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country =   models.ForeignKey(
        'core.Country', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='partners'

    )
    payment_term = models.ForeignKey(
        'accounting.PaymentTerm', on_delete=models.SET_NULL, null=True, blank=True
    )
    preferred_destination_location = models.CharField(
        max_length=200, blank=True,
        help_text="Where goods are delivered when this partner is the customer. "
                  "Free text — not every location exists as a StockLocation record."
    )
    preferred_source_location = models.CharField(
        max_length=200, blank=True,
        help_text="Where goods are delivered when this partner is the customer. "
                  "Free text — not every location exists as a StockLocation record."
    )
    preferred_purchase_currency = models.ForeignKey(
        "core.Currency", on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    supplier_payment_term = models.ForeignKey(
        'accounting.PaymentTerm', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    account_receivable = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )
    account_payable = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'],
                condition=models.Q(company__isnull=False),
                name='unique_partner_name_per_company'
            ),
            models.UniqueConstraint(
                fields=['company', 'tax_id'],
                condition=models.Q(tax_id__isnull=False, company__isnull=False),
                name='unique_partner_tax_id_per_company'
            ),
        ]

    @property
    def is_customer(self):
        return self.partner_type in ('CUSTOMER', 'BOTH')

    @property
    def is_supplier(self):
        return self.partner_type in ('VENDOR', 'BOTH')

    def __str__(self):
        return self.name