from django.db import models
from decimal import Decimal



class BankAccount(models.Model):
    journal = models.ForeignKey("accounting.Journal", on_delete=models.PROTECT,
                                limit_choices_to={'type': 'BANK'})
    account_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=100)
    account_holder = models.CharField(max_length=200)

    def __str__(self):
        return f"{self.bank_name} - {self.account_number}"


class BankStatement(models.Model):
    """
    FIX: Properly split into header (BankStatement) + lines (BankStatementLine).
    The original model collapsed both, making it impossible to represent a
    statement with multiple transactions under one reference.
    """
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE,
                                     related_name='statements')
    date = models.DateField()
    reference = models.CharField(max_length=50)
    opening_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    closing_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
    is_complete = models.BooleanField(default=False,
                                      help_text="Mark True once all lines are reconciled")

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.reference} ({self.date})"


class BankStatementLine(models.Model):
    """Individual transaction on a bank statement."""
    statement = models.ForeignKey("accounting.BankStatement", on_delete=models.CASCADE,
                                  related_name='lines')
    date = models.DateField()
    description = models.CharField(max_length=200)
    reference = models.CharField(max_length=100, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2,
                                 help_text="Positive = credit to bank account, Negative = debit")
    partner = models.ForeignKey("core.Partner", on_delete=models.SET_NULL,
                                null=True, blank=True)
    # Linked journal entry once reconciled
    account_move = models.ForeignKey("accounting.AccountMove", on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='+')
    is_reconciled = models.BooleanField(default=False)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.date} | {self.description} | {self.amount}"

