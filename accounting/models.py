# from datetime import datetime, timedelta
# from django.conf import settings
# from django.db import models, transaction
# from django.core.exceptions import ValidationError
# from django.utils import timezone
# from decimal import Decimal
# from django.db.models import Sum, Q
# from .services import Period_validators
#
#
# # ---------------------------
# # Analytic Accounting
# # ---------------------------
# class AnalyticAccount(models.Model):
#     code = models.CharField(max_length=20, unique=True)
#     name = models.CharField(max_length=100)
#     type = models.CharField(max_length=20, choices=[
#         ('PROJECT', 'Project'),
#         ('DEPARTMENT', 'Department'),
#         ('COST_CENTER', 'Cost Center'),
#     ])
#     is_active = models.BooleanField(default=True)
#
#     def __str__(self):
#         return f"{self.code} - {self.name}"
#
#
# class AnalyticLine(models.Model):
#     """
#     FIX: Removed the direct analytic_account FK from JournalLine.
#     This table is the single place for analytic distribution, and it
#     supports splitting one journal line across multiple analytic accounts.
#     """
#     analytic_account = models.ForeignKey(AnalyticAccount, on_delete=models.CASCADE,
#                                          related_name='lines')
#     move_line = models.ForeignKey(AccountMoveLine, on_delete=models.CASCADE,
#                                      related_name='analytic_lines')
#     percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('100'),
#                                      help_text="Percentage of the journal line amount (sum must = 100)")
#     amount = models.DecimalField(max_digits=15, decimal_places=2)
#
#     def __str__(self):
#         return f"{self.analytic_account.name}: {self.amount}"
#
#
# # ---------------------------
# # Bank and Cash Management
# # ---------------------------
#
# # ---------------------------
# # Fixed Assets
# # ---------------------------
# class Asset(models.Model):
#     DEPRECIATION_METHODS = [
#         ('SL', 'Straight Line'),
#         ('DB', 'Declining Balance'),
#     ]
#     # NEW: asset lifecycle core prevents depreciation on disposed assets
#     STATE_CHOICES = [
#         ('DRAFT', 'Draft'),
#         ('RUNNING', 'Running'),
#         ('DISPOSED', 'Disposed'),
#     ]
#     code = models.CharField(max_length=50, unique=True)
#     name = models.CharField(max_length=200)
#     core = models.CharField(max_length=20, choices=STATE_CHOICES, default='DRAFT')
#     purchase_date = models.DateField()
#     purchase_value = models.DecimalField(max_digits=15, decimal_places=2)
#     salvage_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
#     depreciation_method = models.CharField(max_length=2, choices=DEPRECIATION_METHODS)
#     useful_life_years = models.IntegerField()
#     # NEW: the balance-sheet account that carries the asset at cost
#     account_asset = models.ForeignKey(Account, on_delete=models.PROTECT,
#                                       related_name='assets_cost',
#                                       help_text="Asset at cost (balance sheet)")
#     account_depreciation = models.ForeignKey(Account, on_delete=models.PROTECT,
#                                              related_name='assets_depreciation',
#                                              help_text="Depreciation expense (P&L)")
#     account_accumulated_depr = models.ForeignKey(Account, on_delete=models.PROTECT,
#                                                  related_name='assets_accumulated',
#                                                  help_text="Accumulated depreciation (balance sheet, contra-asset)")
#     # NEW: traceability — which journal entry (purchase bill) created this asset
#     account_move = models.ForeignKey(AccountMove, on_delete=models.SET_NULL,
#                                              null=True, blank=True, related_name='+',
#                                              help_text="The purchase entry that originated this asset")
#     accumulated_depreciation = models.DecimalField(max_digits=15, decimal_places=2,
#                                                    default=Decimal('0'))
#     is_active = models.BooleanField(default=True)
#
#     def __str__(self):
#         return f"{self.code} - {self.name}"
#
#     def net_book_value(self):
#         return self.purchase_value - self.accumulated_depreciation
#
#
# class AssetDepreciationLine(models.Model):
#     """
#     NEW: Individual depreciation run record.
#     Storing only accumulated_depreciation on Asset is not auditable —
#     you need a line per period to see when each charge was posted.
#     """
#     asset = models.ForeignKey(Asset, on_delete=models.CASCADE,
#                               related_name='depreciation_lines')
#     sequence = models.IntegerField()
#     depreciation_date = models.DateField()
#     amount = models.DecimalField(max_digits=15, decimal_places=2)
#     accumulated_value = models.DecimalField(max_digits=15, decimal_places=2)
#     remaining_value = models.DecimalField(max_digits=15, decimal_places=2)
#     account_move = models.ForeignKey(AccountMove, on_delete=models.SET_NULL,
#                                       null=True, blank=True, related_name='+')
#     is_posted = models.BooleanField(default=False)
#
#     class Meta:
#         ordering = ['sequence']
#         unique_together = ['asset', 'sequence']
#
#     def __str__(self):
#         return f"{self.asset.code} - dep #{self.sequence} ({self.depreciation_date}): {self.amount}"
#
#
# # ---------------------------
# # Deferred Revenue / Expenses
# # ---------------------------
# class DeferredLine(models.Model):
#     # NEW: distinguish deferred revenue from prepaid expense
#     DEFERRED_TYPES = [
#         ('REVENUE', 'Deferred Revenue'),
#         ('EXPENSE', 'Prepaid Expense'),
#     ]
#     move_line = models.ForeignKey(AccountMoveLine, on_delete=models.CASCADE,
#                                      related_name='deferred_lines')
#     deferred_type = models.CharField(max_length=20, choices=DEFERRED_TYPES)
#     start_date = models.DateField()
#     end_date = models.DateField()
#     amount = models.DecimalField(max_digits=15, decimal_places=2)
#     recognized = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0'))
#
#     def __str__(self):
#         return f"Deferred {self.deferred_type} {self.amount} ({self.start_date} → {self.end_date})"
#
#     @property
#     def remaining(self):
#         return self.amount - self.recognized
#
#
# # ---------------------------
# # Budgets
# # ---------------------------
# class Budget(models.Model):
#     company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='budgets')
#     name = models.CharField(max_length=100)           # e.g. "FY2025 Annual"
#     date_from = models.DateField()
#     date_to = models.DateField()
#     account = models.ForeignKey(Account, on_delete=models.PROTECT)
#     analytic_account = models.ForeignKey(AnalyticAccount, on_delete=models.SET_NULL,
#                                          null=True, blank=True)
#     amount = models.DecimalField(max_digits=15, decimal_places=2)
#
#     class Meta:
#         unique_together = ['company', 'date_from', 'date_to', 'account', 'analytic_account']
#
#     def __str__(self):
#         return f"{self.name} - {self.account.code}: {self.amount}"
#
#
#
#
#
#
#
