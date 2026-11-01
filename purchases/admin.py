from django.contrib import admin
from purchases.models import PurchaseOrder, PurchaseOrderLine

# ===========================================================================
# Suppliers & Purchase Orders
# ===========================================================================

class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    fields = (
        'product', 'quantity', 'price_unit', 'discount_percent',
        'taxes',
    )
    raw_id_fields = ('product',)
    filter_horizontal = ('taxes',)  # Required for ManyToMany field in inlines

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'partner', 'status', 'issue_date',
        'expected_date', 'total_purchase_amount_display', 'company',
    )
    list_filter = ('status', 'company')
    search_fields = ('reference', 'partner__name', 'notes')
    date_hierarchy = 'issue_date'
    raw_id_fields = ('partner', 'currency', 'created_by', 'company')  # Removed duplicate 'partner'
    readonly_fields = ('created_at', 'updated_at', 'total_purchase_amount_display')
    inlines = [PurchaseOrderLineInline]

    fieldsets = (
        ('Document', {
            'fields': ('reference', 'partner', 'company', 'currency')
        }),
        ('Dates', {
            'fields': ('issue_date', 'expected_date', 'created_at', 'updated_at')
        }),
        ('Status', {
            'fields': ('status', 'total_purchase_amount_display')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('Audit', {
            'fields': ('created_by',),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Total Amount')
    def total_purchase_amount_display(self, obj):
        return obj.total_purchase_amount

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('partner', 'company')


@admin.register(PurchaseOrderLine)
class PurchaseOrderLineAdmin(admin.ModelAdmin):
    class Media:
        js = ('js/purchases/row_duplicates_check.js',)

    list_display = ('product', 'purchase_order', 'quantity', 'price_unit', 'discount_percent')
    list_filter = ('purchase_order',)
    search_fields = ('product__name', 'quantity', 'price_unit', 'discount_percent')  # Fixed FK lookup
    raw_id_fields = ('product', 'purchase_order')  # Added purchase_order