from sales.models import (
    SalesOrder,SalesOrderLine

)
from django.contrib import admin




class SalesOrderLineInline(admin.TabularInline):
    model  = SalesOrderLine
    fk_name = "sales_order"
    extra  = 0
    fields = ('id','product', 'quantity' ,'price_unit', 'discount_percent', 'product_cost','taxes',)
    raw_id_fields = ('quant',)
    readonly_fields = ('qty_fulfilled','qty_invoiced')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('quant__product')


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    class Media:
        js = ('js/general/row_duplicates_check.js',)

    list_display  = (
        'id','order_number', 'partner', 'issue_date',
        'status', 'amount_total', 'company',
    )
    list_filter   = ('status', 'company')
    search_fields = ('order_number', 'customer__name', 'notes')
    date_hierarchy = 'issue_date'
    raw_id_fields = ('partner', 'fulfillment_location', 'company', 'currency', 'created_by')
    readonly_fields = ('amount_total', 'created_at')
    inlines = [SalesOrderLineInline]

    fieldsets = (
        ('Document', {
            'fields': ('order_number', 'partner', 'company', 'currency')
        }),
        ('Dates', {
            'fields': ('issue_date', 'created_at')
        }),
        ('Logistics', {
            'fields': ('fulfillment_location',)
        }),
        ('Status & Totals', {
            'fields': ('status', 'amount_total',)
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



@admin.register(SalesOrderLine)
class SalesOrderLineAdmin(admin.ModelAdmin):
    model = SalesOrderLine

    list_display = ('id','product','quantity')

