from django.db import models


class CompanyAccountSetting(models.Model):
    SETTING_KEYS = [
        ('default_receivable', 'Default Receivable'),
        ('default_payable', 'Default Payable'),
        ('default_cash', 'Default Cash'),
        ('default_bank', 'Default Bank'),
        ('default_tax_receivable', 'Default Tax Receivable'),
        ('default_tax_payable', 'Default Tax Payable'),
        ('default_prepaid', 'Default Prepaid Expense'),
        ('default_unearned_revenue', 'Default Unearned Revenue'),
        ('default_customer_prepayments', 'Default Customer Prepayments'),
        ('default_vendor_advances', 'Default Vendor Advances'),
        ('default_inventory_revaluation_gain', 'Default Inventory Revaluation Gain Account'),
        ('default_inventory_revaluation_expense', 'Default Inventory Revaluation Expense Account'),
        ('default_inventory_adjustment_gain', 'Default Inventory Adjustment Gain'),
        ('default_inventory_adjustment_expense', 'Default Inventory Adjustment Expense'),
        ('default_price_difference_account', 'Default Purchase Price Difference Account'),
        ('default_cogs_account', 'Default Cost of Goods Sold Account'),
        ('default_revenue_account', 'Default Sales Revenue Account'),
        ('default_retained_earnings', 'Default Retained Earnings'),
        ('default_current_year_earnings', 'Default Current Year Earnings'),
        ('default_exchange_gain_account', 'Default Exchange Gain Account'),
        ('default_exchange_loss_account', 'Default Exchange Loss Account'),
        ('default_cash_difference_gain', 'Cash Difference Gain'),
        ('default_cash_difference_loss', 'Cash Difference Loss'),
        ('default_customer_credit_note_account', 'Default Customer Credit Note Account'),
        ('default_vendor_credit_note_account', 'Default Vendor Credit Note Account'),
        ('default_inventory_valuation_account', 'Default Inventory Valuation Account'),
        ('default_stock_input_account', 'Default Stock Input / GRNI Account'),
        ('default_stock_output_account', 'Default Stock Output Account'),
    ]

    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='account_settings')
    key = models.CharField(max_length=50, choices=SETTING_KEYS)
    account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT)

    class Meta:
        unique_together = ['company', 'key']


class CompanyJournalSetting(models.Model):
    SETTING_KEYS = [
        ('default_return_journal', 'Default Return Journal'),
        ('default_cash_refund_journal', 'Default Cash Refund Journal'),
        ('default_store_credit_journal', 'Default Store Credit Journal'),
    ]

    company = models.ForeignKey('core.Company', on_delete=models.CASCADE, related_name='journal_settings')
    key = models.CharField(max_length=50, choices=SETTING_KEYS)
    journal = models.ForeignKey('accounting.Journal', on_delete=models.PROTECT, related_name='+')

    class Meta:
        unique_together = ['company', 'key']