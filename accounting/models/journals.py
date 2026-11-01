from django.db import models, transaction


class Journal(models.Model):
    JOURNAL_TYPES = [
        ('SALE', 'Sales'),
        ('PURCHASE', 'Purchase'),
        ('CASH', 'Cash'),
        ('BANK', 'Bank'),
        ('INVENTORY', 'Inventory'),
        ('GENERAL', 'General'),
        ("MISC", "Miscellaneous")

    ]
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name='journals')
    code = models.CharField(max_length=10)
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=JOURNAL_TYPES)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT,
                                 null=True, blank=True,
                                 help_text="Leave blank to use company currency")
    default_debit_account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT,
                                              null=True, blank=True, related_name='+')
    default_credit_account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT,
                                               null=True, blank=True, related_name='+')
    suspense_account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT,
                                         null=True, blank=True, related_name='+',
                                         help_text="Temporary account for unmatched bank statement lines")
    sequence = models.IntegerField(default=1, help_text="Next entry number for this journal")
    notes = models.TextField(null=True, blank=True)
    next_payment_number = models.IntegerField(default=1, help_text="Next number to use for payments in this journal")

    # on Journal
    outstanding_receipts_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.PROTECT,
        related_name='+',
        help_text="Clearing account for INCOMING payments awaiting bank/statement confirmation.",
    )
    outstanding_payments_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.PROTECT,
        related_name='+',
        help_text="Clearing account for OUTGOING payments awaiting bank/statement confirmation.",
    )
    requires_outstanding_reconciliation = models.BooleanField(
        default=False,
        help_text=(
            "True for journals where a payment isn't confirmed by the payment "
            "record alone — bank/mobile statement import must later match it. "
            "False for journals where recording the payment IS the confirmation "
            "(e.g. a physical cash drawer)."
        ),
    )


    class Meta:
        unique_together = ['company', 'code']

    def get_next_number(self):
        with transaction.atomic():
            journal = Journal.objects.select_for_update().get(pk=self.pk)
            num = journal.sequence
            journal.sequence += 1
            journal.save(update_fields=['sequence'])
        return f"{self.code}-{num:06d}"


    def get_liquidity_account(self, payment_type):
        if not self.requires_outstanding_reconciliation:
            return self.default_debit_account if payment_type == 'INCOMING' else self.default_credit_account

        if payment_type == 'INCOMING':
            return self.outstanding_receipts_account or self.default_debit_account
        return self.outstanding_payments_account or self.default_credit_account

    def get_next_payment_number(self):
        with transaction.atomic():
            journal = Journal.objects.select_for_update().get(pk=self.pk)
            num = journal.next_payment_number
            journal.next_payment_number += 1
            journal.save(update_fields=['next_payment_number'])
        return f"{self.code}-PAY-{num:06d}"

    def __str__(self):
        return f"{self.code} - {self.name}"



