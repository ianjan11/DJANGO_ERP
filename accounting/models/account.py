from django.db import models
from decimal import Decimal
from django.db.models import Sum


class AccountType(models.Model):
    INTERNAL_GROUP_CHOICES = [
        ('ASSET', 'Asset'),
        ('LIABILITY', 'Liability'),
        ('EQUITY', 'Equity'),
        ('INCOME', 'Income'),
        ('EXPENSE', 'Expense'),
    ]
    name = models.CharField(max_length=50, unique=True)
    code = models.CharField(max_length=50, unique=True)   # e.g. "account_type_liquidity"
    internal_group = models.CharField(max_length=20, choices=INTERNAL_GROUP_CHOICES)

    def __str__(self):
        return f"{self.name} ({self.internal_group})"


class Account(models.Model):
    INTERNAL_TYPE_CHOICES = [
        ('receivable', 'Receivable'),
        ('payable', 'Payable'),
        ('liquidity', 'Liquidity'),
        ('other', 'Other'),
    ]

    code = models.CharField(max_length=10)
    name = models.CharField(max_length=100)
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT,
                                     related_name='accounts')
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT,
                                 null=True, blank=True,
                                 help_text="Force all moves on this account to use this currency")
    parent = models.ForeignKey('self', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='children')
    internal_type = models.CharField(
        max_length=20,
        choices=INTERNAL_TYPE_CHOICES,
        default='other'
    )
    is_control_account = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    allow_reconciliation = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='accounts')

    class Meta:
        ordering = ['code']
        # unique_together was a duplicate of this constraint, so it is removed.
        constraints = [
            models.UniqueConstraint(fields=['company', 'code'], name='unique_account_code_per_company')
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def full_name(self):
        names = [self.name]
        p = self.parent
        while p:
            names.insert(0, p.name)
            p = p.parent
        return " / ".join(names)

    def get_balance(self, date_from=None, date_to=None):
        from accounting.models import AccountMove, AccountMoveLine

        # FIX: State.POSTED is 'posted' (lowercase), so the old 'POSTED' filter matched
        # nothing and every balance was 0. FIX: AccountMove has issue_date, not date.
        lines = AccountMoveLine.objects.filter(
            account=self,
            move__state=AccountMove.State.POSTED,
        )
        if date_from:
            lines = lines.filter(move__issue_date__gte=date_from)
        if date_to:
            lines = lines.filter(move__issue_date__lte=date_to)

        agg = lines.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit')
        )
        dr = agg['total_debit'] or Decimal('0')
        cr = agg['total_credit'] or Decimal('0')

        internal_group = self.account_type.internal_group
        if internal_group in ('ASSET', 'EXPENSE'):
            return dr - cr
        return cr - dr