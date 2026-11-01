from django.contrib import admin
from django.utils.html import format_html

from accounting.models import (
    AccountType, Account,
    PaymentTermLine,
    CompanyAccountSetting,
    Journal,
    AccountMove, AccountMoveLine,
    TaxGroup, Tax, TaxLine,
    PartialReconcile,
    BankAccount, BankStatement, BankStatementLine, Payment, PaymentInvoiceLine, PaymentTerm
)


# ===========================================================================
# Shared helpers
# ===========================================================================

def _money(amount, symbol=""):
    # Ensure it's a float/decimal
    val = amount or 0

    # Convert to string with 2 decimal places FIRST
    str_val = "{:,.2f}".format(float(val))

    # Then return the safe HTML
    return format_html("{} {}", symbol, str_val)

def _badge(label, color):
    """Coloured pill badge for core fields."""
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 9px;'
        'border-radius:3px;font-size:11px;font-weight:600;'
        'white-space:nowrap">{}</span>',
        color, label,
    )


# Colour maps — keep them at module level so multiple admins can share them
_MOVE_COLORS  = {"draft": "#6c757d", "posted": "#28a745", "cancelled": "#dc3545"}
_PAY_COLORS   = {"not_paid": "#dc3545", "partial": "#fd7e14", "paid": "#28a745"}
_ASSET_COLORS = {"DRAFT": "#6c757d", "RUNNING": "#28a745", "DISPOSED": "#adb5bd"}




@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display  = ("name", "internal_group", "code")
    list_filter   = ("internal_group",)
    search_fields = ("name",)
    ordering      = ("internal_group", "name", "code")

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "account_type", "company",
        "parent", "is_control_account", "allow_reconciliation",
        "is_active","internal_type"
    )
    list_filter = (
        "company", "account_type__internal_group",
        "is_active", "is_control_account", "allow_reconciliation",
    )
    search_fields = ("code", "name")
    ordering      = ("company", "code")
    autocomplete_fields = ("company", "account_type", "currency", "parent")
    readonly_fields = ("full_name",)
    fieldsets = (
        ("Identity", {
            "fields": ("company", "code", "name", "full_name", "account_type", "parent"),
        }),
        ("Settings", {
            "fields": ("currency", "is_control_account", "allow_reconciliation", "is_active","internal_type",),
        }),
        ("Description", {"fields": ("description",), "classes": ("collapse",)}),
    )

    # @admin.display(description="Balance")
    # def balance_display(self, obj):
    #     sym = obj.currency.symbol if obj.currency else ""
    #     return _money(obj.get_balance(), sym)

# ===========================================================================
# Payment Terms
# ===========================================================================

class PaymentTermLineInline(admin.TabularInline):
    model    = PaymentTermLine
    extra    = 1
    fields   = ("sequence", "computation_type", "value", "days",
                "discount_days", "discount_percent")
    ordering = ("sequence",)


@admin.register(PaymentTerm)
class PaymentTermAdmin(admin.ModelAdmin):
    list_display  = ("name", "note", "line_count")
    search_fields = ("name",)
    inlines       = [PaymentTermLineInline]

    @admin.display(description="Lines")
    def line_count(self, obj):
        return obj.lines.count()


# ===========================================================================
# Company & Settings
# ===========================================================================

class CompanyAccountSettingInline(admin.TabularInline):
    model               = CompanyAccountSetting
    extra               = 0
    fields              = ("key", "account")
    autocomplete_fields = ("account",)




@admin.register(CompanyAccountSetting)
class CompanyAccountSettingAdmin(admin.ModelAdmin):
    list_display  = ("company", "key", "account")
    list_filter   = ("company", "key")
    search_fields = ("company__name", "account__code", "account__name")
    autocomplete_fields = ("company", "account")


# ===========================================================================
# Journals
# ===========================================================================

@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display  = (
        "code", "name", "type", "company",
        "currency", "sequence", "next_payment_number",
    )
    list_filter   = ("company", "type")
    search_fields = ("code", "name")
    ordering      = ("company", "code")
    autocomplete_fields = (
        "company", "currency",
        "default_debit_account", "default_credit_account", "suspense_account",
        'outstanding_receipts_account','outstanding_payments_account',
    )
    fieldsets = (
        ("Identity", {"fields": ("company", "code", "name", "type", "currency")}),
        ("Default Accounts", {
            "fields": ("default_debit_account", "default_credit_account", "suspense_account",
                       'outstanding_receipts_account','outstanding_payments_account',
                       'requires_outstanding_reconciliation',),
        }),
        ("Sequences", {
            "fields": ("sequence", "next_payment_number"),
            "description": "Auto-incremented — edit only to correct gaps.",
        }),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
    )


# ===========================================================================
# Account Move  (Invoice / Bill / Entry / Payment)
# ===========================================================================

class AccountMoveLineInline(admin.TabularInline):
    model               = AccountMoveLine
    extra               = 0
    fields              = (
        "account", "partner", "memo",
        "debit", "credit",
        "original_amount", "foreign_currency", "date", 'taxes',
    )
    autocomplete_fields = ("account", "partner", "foreign_currency")
    show_change_link    = True
    ordering            = ("id",)

    def get_readonly_fields(self, request, obj=None):
        # Lock every line field once the parent move is posted
        if obj and obj.state == "posted":
            return [
                "account", "partner", "memo",
                "debit", "credit", "original_amount", "foreign_currency", "date", 'taxes',
            ]
        return []

    def has_add_permission(self, request, obj=None):
        return False if (obj and obj.state == "posted") else super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False if (obj and obj.state == "posted") else super().has_delete_permission(request, obj)


# Fields that must be locked once a move is posted
_MOVE_LOCKED_FIELDS = [
    "move_type", "journal", "company", "issue_date",
    "partner", "currency", "currency_rate",
    "reversal_of", "payment_term",
]


@admin.register(AccountMove)
class AccountMoveAdmin(admin.ModelAdmin):
    list_display  = (
        "name", "move_type_display", "issue_date", "partner",
        "journal", "company",
        "amount_total_display", "payment_state_badge", "state_badge","amount_residual","move_type"
    )
    list_filter   = (
        "company", "journal__type", "move_type", "payment_state", "issue_date",
    )
    search_fields  = ("name", "ref", "partner__name", "narration")
    ordering       = ("-issue_date", "-id")
    date_hierarchy = "issue_date"
    inlines        = [AccountMoveLineInline]
    autocomplete_fields = (
        "partner", "currency", "company",
        "journal", "reversal_of", "payment_term",
    )
    readonly_fields = (
        # Always read-only — system managed
        "name",
        "amount_total", "amount_untaxed", "amount_tax",
        "paid_amount", "payment_state","move_type",
        "reconciled", "reconciliation_date", "posted_at", "posted_by",
        "created_by", "created_at",
        "is_balanced_display",
    )
    fieldsets = (
        ("Document", {
            "fields": (
                "name","state", "move_type", "journal", "company",
                "issue_date", "due_date", "partner",
                "payment_term", "ref", "narration","origin_type", "origin_id","fulfillment_location",
            ),
        }),
        ("Currency", {
            "fields": ("currency", "currency_rate"),
        }),
        ("Totals (computed)", {
            "fields": (
                "amount_untaxed", "amount_tax", "amount_total",
                "is_balanced_display",
            ),
        }),
        ("Payment Status (cache)", {
            "fields": ("payment_state", "paid_amount", "reconciled", "reconciliation_date"),
            "description": "These fields are maintained by the system — do not edit manually.",
        }),
        ("Workflow", {
            "fields": ("posted_by", "posted_at"),
        }),
        ("Reversal", {
            "fields": ("reversal_of",),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields": ("created_by", "created_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Type")
    def move_type_display(self, obj):
        return obj.get_move_type_display()

    @admin.display(description="Total")
    def amount_total_display(self, obj):
        sym = obj.company.currency.symbol if obj.currency else ""
        raw_amount = obj.amount_total
        return _money(raw_amount, sym)

    @admin.display(description="State")
    def state_badge(self, obj):
        return _badge(obj.state, _MOVE_COLORS.get(obj.state, "#6c757d"))

    @admin.display(description="Payment")
    def payment_state_badge(self, obj):
        return _badge(obj.payment_state, _PAY_COLORS.get(obj.payment_state, "#6c757d"))

    @admin.display(description="Balanced?", boolean=True)
    def is_balanced_display(self, obj):
        return obj.is_balanced()

    def get_readonly_fields(self, request, obj=None):
        base = list(self.readonly_fields)
        if obj and obj.state == "posted":
            base += _MOVE_LOCKED_FIELDS
        return base

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AccountMoveLine)
class AccountMoveLineAdmin(admin.ModelAdmin):
    list_display  = (
        "move_name", "account", "partner",
        "debit_display", "credit_display",
        "foreign_currency", "original_amount", "date", "memo","reconciled","line_type",
    )
    list_filter   = (
        "move__company", "move__journal",
        "move__state", "account__account_type__internal_group",
    )
    search_fields = (
        "account__code", "account__name",
        "partner__name", "memo", "move__name",
    )
    ordering       = ("-move__issue_date", "-id")
    date_hierarchy = "date"
    autocomplete_fields = ("move", "account", "partner", "foreign_currency")

    @admin.display(description="Move", ordering="move__name")
    def move_name(self, obj):
        return obj.move.name or f"Move #{obj.move_id}"

    @admin.display(description="Debit")
    def debit_display(self, obj):
        return _money(obj.debit) if obj.debit else "—"

    @admin.display(description="Credit")
    def credit_display(self, obj):
        return _money(obj.credit) if obj.credit else "—"


# ===========================================================================
# Analytic Accounting
# ===========================================================================

# class AnalyticLineInline(admin.TabularInline):
#     model               = AnalyticLine
#     extra               = 0
#     fields              = ("analytic_account", "percentage", "amount")
#     autocomplete_fields = ("analytic_account",)
#
#
# @admin.register(AnalyticAccount)
# class AnalyticAccountAdmin(admin.ModelAdmin):
#     list_display  = ("code", "name", "type", "is_active", "total_amount")
#     list_filter   = ("type", "is_active")
#     search_fields = ("code", "name")
#     ordering      = ("code",)
#
#     @admin.display(description="Total Distributed")
#     def total_amount(self, obj):
#         total = obj.lines.aggregate(s=Sum("amount"))["s"] or Decimal("0")
#         return _money(total)
#
#
# @admin.register(AnalyticLine)
# class AnalyticLineAdmin(admin.ModelAdmin):
#     list_display  = ("analytic_account", "move_line", "percentage", "amount_display")
#     list_filter   = ("analytic_account",)
#     search_fields = ("analytic_account__code", "analytic_account__name")
#     autocomplete_fields = ("analytic_account", "move_line")
#
#     @admin.display(description="Amount")
#     def amount_display(self, obj):
#         return _money(obj.amount)


# ===========================================================================
# Taxes
# ===========================================================================

@admin.register(TaxGroup)
class TaxGroupAdmin(admin.ModelAdmin):
    list_display  = ("name", "sequence")
    ordering      = ("sequence",)
    search_fields = ("name",)


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
    list_display  = (
        "name", "type_tax_use", "computation", "rate_display",
        "sequence", "price_include", "include_base_amount",
        "tax_group", "is_active",
    )
    list_filter   = (
        "type_tax_use", "computation", "tax_group",
        "is_active", "price_include", "include_base_amount",
    )
    search_fields = ("name",)
    ordering      = ("sequence", "id")
    autocomplete_fields = ("account", "account_refund", "tax_group", "parent_tax")
    fieldsets = (
        ("Identity",  {"fields": ("name", "company","type_tax_use", "computation", "rate", "sequence", "tax_group")}),
        ("Accounts",  {"fields": ("account", "account_refund")}),
        ("Behaviour", {"fields": ("price_include", "include_base_amount", "parent_tax")}),
        ("Status",    {"fields": ("is_active",)}),
    )

    @admin.display(description="Rate")
    def rate_display(self, obj):
        return f"{obj.rate:.2f}%"


@admin.register(TaxLine)
class TaxLineAdmin(admin.ModelAdmin):
    list_display  = ("tax", "move_line", "base_amount_display", "tax_amount_display", "source_line")
    list_filter   = ("tax",)
    search_fields = ("tax__name", "move_line__move__name")
    # System-generated — never manually edited
    readonly_fields = ("tax", "move_line", "base_amount", "tax_amount", "source_line")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Base")
    def base_amount_display(self, obj):
        return _money(obj.base_amount)

    @admin.display(description="Tax")
    def tax_amount_display(self, obj):
        return _money(obj.tax_amount)


# ===========================================================================
# Reconciliation
# ===========================================================================

@admin.register(PartialReconcile)
class PartialReconcileAdmin(admin.ModelAdmin):
    list_display  = (
        "debit_line", "credit_line",
        "amount_display", "fcy_amount_display",
        "currency", "date", "created_by",
    )
    list_filter    = ("currency", "date")
    search_fields  = (
        "debit_line__move__name", "credit_line__move__name",
        "debit_line__account__code",
    )
    ordering       = ("-date",)
    date_hierarchy = "date"
    # All fields read-only — reconciliations are created programmatically
    readonly_fields = (
        "debit_line", "credit_line",
        "amount", "amount_currency", "currency",
        "date", "created_by",
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Amount")
    def amount_display(self, obj):
        return _money(obj.amount)

    @admin.display(description="FCY Amount")
    def fcy_amount_display(self, obj):
        return _money(obj.amount_currency) if obj.amount_currency else "—"


# ===========================================================================
# Bank & Cash
# ===========================================================================

class BankStatementLineInline(admin.TabularInline):
    model               = BankStatementLine
    extra               = 0
    fields              = (
        "date", "description", "reference",
        "amount", "partner", "account_move", "is_reconciled",
    )
    autocomplete_fields = ("partner", "account_move")
    show_change_link    = True
    ordering            = ("date",)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display  = ("bank_name", "account_number", "account_holder", "journal")
    search_fields = ("bank_name", "account_number", "account_holder")
    autocomplete_fields = ("journal",)


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display  = (
        "reference", "bank_account", "date",
        "opening_display", "closing_display",
        "line_count", "unreconciled_count", "is_complete",
    )
    list_filter    = ("bank_account", "is_complete", "date")
    search_fields  = ("reference", "bank_account__account_number")
    ordering       = ("-date",)
    date_hierarchy = "date"
    inlines        = [BankStatementLineInline]
    readonly_fields = ("opening_balance", "closing_balance")

    @admin.display(description="Opening")
    def opening_display(self, obj):
        return _money(obj.opening_balance)

    @admin.display(description="Closing")
    def closing_display(self, obj):
        return _money(obj.closing_balance)

    @admin.display(description="Lines")
    def line_count(self, obj):
        return obj.lines.count()

    @admin.display(description="Unreconciled")
    def unreconciled_count(self, obj):
        n = obj.lines.filter(is_reconciled=False).count()
        color = "#dc3545" if n else "#28a745"
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>', color, n
        )


@admin.register(BankStatementLine)
class BankStatementLineAdmin(admin.ModelAdmin):
    list_display  = (
        "date", "statement", "description", "reference",
        "amount_display", "partner", "is_reconciled",
    )
    list_filter    = ("statement__bank_account", "is_reconciled", "date")
    search_fields  = ("description", "reference", "partner__name")
    ordering       = ("-date",)
    date_hierarchy = "date"
    autocomplete_fields = ("statement", "partner", "account_move")

    @admin.display(description="Amount")
    def amount_display(self, obj):
        color = "#28a745" if obj.amount >= 0 else "#dc3545"
        return format_html(
            '<span style="color:{};font-family:monospace">{:,.2f}</span>',
            color, obj.amount,
        )


# ===========================================================================
# Fixed Assets
# ===========================================================================
#
# class AssetDepreciationLineInline(admin.TabularInline):
#     model           = AssetDepreciationLine
#     extra           = 0
#     fields          = (
#         "sequence", "depreciation_date", "amount",
#         "accumulated_value", "remaining_value",
#         "account_move", "is_posted",
#     )
#     # Schedule is computed — protect the amounts, only posting fields are editable
#     readonly_fields = (
#         "sequence", "depreciation_date",
#         "amount", "accumulated_value", "remaining_value",
#     )
#     show_change_link = True
#     ordering         = ("sequence",)
#
#
# @admin.register(Asset)
# class AssetAdmin(admin.ModelAdmin):
#     list_display  = (
#         "code", "name", "state_badge",
#         "purchase_date", "cost_display",
#         "accumulated_display", "nbv_display",
#         "depreciation_method", "useful_life_years", "is_active",
#     )
#     list_filter   = ("core", "depreciation_method", "is_active")
#     search_fields = ("code", "name")
#     ordering      = ("code",)
#     readonly_fields = ("accumulated_depreciation", "nbv_display")
#     autocomplete_fields = (
#         "account_asset", "account_depreciation",
#         "account_accumulated_depr", "account_move",
#     )
#     inlines   = [AssetDepreciationLineInline]
#     fieldsets = (
#         ("Identity",    {"fields": ("code", "name", "core", "is_active")}),
#         ("Valuation", {
#             "fields": (
#                 "purchase_date", "purchase_value", "salvage_value",
#                 "accumulated_depreciation", "nbv_display",
#             ),
#         }),
#         ("Depreciation", {"fields": ("depreciation_method", "useful_life_years")}),
#         ("GL Accounts",  {"fields": ("account_asset", "account_depreciation", "account_accumulated_depr")}),
#         ("Traceability", {"fields": ("account_move",), "classes": ("collapse",)}),
#     )
#
#     @admin.display(description="State")
#     def state_badge(self, obj):
#         return _badge(obj.core, _ASSET_COLORS.get(obj.core, "#6c757d"))
#
#     @admin.display(description="Cost")
#     def cost_display(self, obj):
#         return _money(obj.purchase_value)
#
#     @admin.display(description="Accum. Depr.")
#     def accumulated_display(self, obj):
#         return _money(obj.accumulated_depreciation)
#
#     @admin.display(description="Net Book Value")
#     def nbv_display(self, obj):
#         return _money(obj.net_book_value())
#
#
# @admin.register(AssetDepreciationLine)
# class AssetDepreciationLineAdmin(admin.ModelAdmin):
#     list_display  = (
#         "asset", "sequence", "depreciation_date",
#         "amount_display", "accumulated_display",
#         "remaining_display", "is_posted",
#     )
#     list_filter    = ("is_posted", "asset__state")
#     search_fields  = ("asset__code", "asset__name")
#     ordering       = ("asset", "sequence")
#     date_hierarchy = "depreciation_date"
#     readonly_fields = (
#         "asset", "sequence", "depreciation_date",
#         "amount", "accumulated_value", "remaining_value",
#     )
#     autocomplete_fields = ("account_move",)
#
#     @admin.display(description="Amount")
#     def amount_display(self, obj):
#         return _money(obj.amount)
#
#     @admin.display(description="Accumulated")
#     def accumulated_display(self, obj):
#         return _money(obj.accumulated_value)
#
#     @admin.display(description="Remaining")
#     def remaining_display(self, obj):
#         return _money(obj.remaining_value)


# ===========================================================================
# Deferred Revenue / Expenses
# ===========================================================================
#
# @admin.register(DeferredLine)
# class DeferredLineAdmin(admin.ModelAdmin):
#     list_display  = (
#         "move_line", "deferred_type",
#         "start_date", "end_date",
#         "amount_display", "recognized_display",
#         "remaining_display", "progress_display",
#     )
#     list_filter    = ("deferred_type",)
#     search_fields  = ("move_line__move__name", "move_line__account__code")
#     ordering       = ("start_date",)
#     date_hierarchy = "start_date"
#     readonly_fields = ("remaining_display", "progress_display")
#     autocomplete_fields = ("move_line",)
#
#     @admin.display(description="Amount")
#     def amount_display(self, obj):
#         return _money(obj.amount)
#
#     @admin.display(description="Recognized")
#     def recognized_display(self, obj):
#         return _money(obj.recognized)
#
#     @admin.display(description="Remaining")
#     def remaining_display(self, obj):
#         return _money(obj.remaining)
#
#     @admin.display(description="Progress")
#     def progress_display(self, obj):
#         if not obj.amount:
#             return "—"
#         pct = (obj.recognized / obj.amount * 100).quantize(Decimal("0.1"))
#         color = "#28a745" if pct >= 100 else "#007bff"
#         return format_html(
#             '<span style="color:{};font-family:monospace;font-weight:600">{}%</span>',
#             color, pct,
#         )


# ===========================================================================
# Budgets
# ===========================================================================

# @admin.register(Budget)
# class BudgetAdmin(admin.ModelAdmin):
#     list_display  = (
#         "name", "company", "date_from", "date_to",
#         "account", "analytic_account", "amount_display",
#     )
#     list_filter    = ("company", "analytic_account")
#     search_fields  = ("name", "account__code", "account__name", "company__name")
#     ordering       = ("company", "date_from", "account")
#     date_hierarchy = "date_from"
#     autocomplete_fields = ("company", "account", "analytic_account")
#
#     @admin.display(description="Budget Amount")
#     def amount_display(self, obj):
#         return _money(obj.amount)


# ===========================================================================
# Payments
# ===========================================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "payment_number","company","date","partner",
        "payment_type","payment_method","currency","residual_amount","ref","is_prepayment",
        "payment_state","posted_at"
    )
    list_filter = ("payment_type","payment_method","payment_number")
    search_fields = ("payment_number",)
    date_hierarchy = "date"

    @admin.display(description="Payment Amount")
    def amount_display(self, obj):
        return _money(obj.amount)

@admin.register(PaymentInvoiceLine)
class PaymentInvoiceLineAdmin(admin.ModelAdmin):
    list_display = (
        'payment', 'invoice_move','amount',
    )





