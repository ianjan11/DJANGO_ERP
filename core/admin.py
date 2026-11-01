from django.contrib import admin
from django.utils.html import format_html

from core.models import Currency, Company, ExchangeRate, Country, Partner
from  accounting.models import CompanyAccountSetting
from core.models.currency import CompanyCurrency

# ===========================================================================
# Shared helpers
# ===========================================================================




# Colour maps — keep them at module level so multiple admins can share them
_MOVE_COLORS  = {"draft": "#6c757d", "posted": "#28a745", "cancelled": "#dc3545"}
_PAY_COLORS   = {"not_paid": "#dc3545", "partial": "#fd7e14", "paid": "#28a745"}
_ASSET_COLORS = {"DRAFT": "#6c757d", "RUNNING": "#28a745", "DISPOSED": "#adb5bd"}


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


# ===========================================================================
# Partners
# ===========================================================================

@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display  = (
        "name", "partner_type", "company",
        "tax_id", "email", "phone", "city", "is_active",
    )
    list_filter   = ("company", "partner_type", "is_active",)
    search_fields = ("name", "tax_id", "email", "phone")
    ordering      = ("company", "name")
    autocomplete_fields = ("company", "payment_term", "account_receivable", "account_payable")
    fieldsets = (
        ("Identity",   {"fields": ("company", "name", "partner_type", "tax_id",
                                   "preferred_source_location")}),
        ("Contact",    {"fields": ("email", "phone", "address", "city", )}),
        ("Accounting", {"fields": ("payment_term", "account_receivable", "account_payable")}),
        ("Status",     {"fields": ("is_active",)}),

    )



# ===========================================================================
# Currency
# ===========================================================================

@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display  = ("code", "name", "symbol", "is_active")
    list_filter   = ("is_active",)
    search_fields = ("code", "name")
    ordering      = ("code",)



@admin.register(CompanyCurrency)
class CompanyCurrencyAdmin(admin.ModelAdmin):
    list_display  = ("currency", "company", "is_active")
    list_filter   = ("is_active",)
    search_fields = ("company", "currency")
    ordering      = ("currency",)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display   = ("currency", "rate", "date", "company")
    list_filter    = ("currency", "company")
    search_fields  = ("currency__code",)
    ordering       = ("-date",)
    date_hierarchy = "date"
    autocomplete_fields = ("currency", "company")



class CompanyAccountSettingInline(admin.TabularInline):
    model               = CompanyAccountSetting
    extra               = 0
    fields              = ("key", "account")
    autocomplete_fields = ("account",)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display  = (
        "code", "currency",
        "fiscal_year_start_month", "fiscal_year_start_day",
        "lock_date", "tax_lock_date", "is_active",
    )
    list_filter   = ("is_active", "currency")
    search_fields = ("code",)
    readonly_fields = ("created_at",)
    inlines       = [CompanyAccountSettingInline]
    fieldsets = (
        ("Identity",        {"fields": ("code", "currency")}),
        ("Fiscal Settings", {"fields": ("fiscal_year_start_month", "fiscal_year_start_day")}),
        ("Lock Dates", {
            "fields": ("lock_date", "tax_lock_date"),
            "description": (
                "lock_date prevents posting on or before this date. "
                "tax_lock_date additionally protects tax lines."
            ),
        }),
        ("Status", {"fields": ("is_active", "created_at")}),
    )


