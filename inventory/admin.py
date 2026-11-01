from django.contrib import admin
from inventory.models import (
    Warehouse, StockLocation, Product, ProductPrice, StockQuant, StockMove,
    ProductsCategory, Uom, UomCategory, StockPicking, StockPickingType, StockLot, StockRoute, StockRule,
    ProcurementGroup
)
from inventory.models.stock_move import StockMoveLine


admin.site.register(StockPickingType)
admin.site.register(StockRoute)
admin.site.register(StockRule)
admin.site.register(ProcurementGroup)



@admin.register(StockPicking)
class StockPickingAdmin(admin.ModelAdmin):
    list_display = ('name', 'picking_type', 'warehouse', 'company', 'partner','created_at', 'scheduled_date',
                    'date_done','source_location', 'dest_location', 'status', 'backorder_of','origin' )
    list_filter = ('status','created_at',)
    search_fields = ('name',)
    raw_id_fields = ('sales_order', 'purchase_order')
    ordering = ('-created_at',)

# ===========================================================================
# Warehouse & Locations
# ===========================================================================

@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display  = ('name', )
    search_fields = ('name',)
    raw_id_fields = ('company',)


@admin.register(StockLocation)
class StockLocationAdmin(admin.ModelAdmin):
    list_display  = ('name', 'warehouse')
    list_filter   = ('warehouse',)
    search_fields = ('name',)
    raw_id_fields = ('warehouse',)


# ===========================================================================
# Products & Pricing
# ===========================================================================

class ProductPriceInline(admin.TabularInline):
    model  = ProductPrice
    extra  = 0
    fields = ('price', 'product_cost', 'start_date', 'end_date', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('-start_date',)

admin.site.register(UomCategory)
admin.site.register(Uom)



@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display  = (
        'name','company' ,'sku', 'category',
        'default_price', 'product_cost', 'profit_margin',
        'max_discount_percent', 'available_stock_display',
    )
    list_filter   = ('category',)
    search_fields = ('name', 'sku', 'description')
    filter_horizontal = ('sales_taxes', 'purchase_taxes')
    raw_id_fields = ('revenue_account', 'cogs_account', )
    readonly_fields = ('available_stock_display', 'reserved_stock_display', 'minimum_price_display', 'created_at', 'updated_at')
    inlines = [ProductPriceInline]

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'uom', 'uom_po','company' ,'sku', 'description', 'category',
                       'costing_method','purchase_method','product_type', 'sales_invoicing_method', 'tracking',)
        }),
        ('Pricing', {
            'fields': (
                'default_price', 'product_cost', 'profit_margin',
                'max_discount_percent', 'minimum_price_display',
            )
        }),
        ('Accounting', {
            'fields': ('revenue_account', 'cogs_account','expense_account',),
            'classes': ('collapse',),
        }),
        ('Taxes', {
            'fields': ('sales_taxes', 'purchase_taxes'),
            'classes': ('collapse',),
        }),
        ('Stock Info', {
            'fields': ('available_stock_display', 'reserved_stock_display'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Available Stock')
    def available_stock_display(self, obj):
        return obj.available_stock()

    @admin.display(description='Reserved Stock')
    def reserved_stock_display(self, obj):
        return obj.reserved_stock()

    @admin.display(description='Minimum Price')
    def minimum_price_display(self, obj):
        return obj.minimum_price()



@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display  = ('product', 'price', 'product_cost', 'start_date', 'end_date')
    list_filter   = ('product',)
    search_fields = ('product__name',)
    date_hierarchy = 'start_date'
    raw_id_fields = ('product',)


# ===========================================================================
# Stock
# ===========================================================================

@admin.register(StockQuant)
class StockQuantAdmin(admin.ModelAdmin):
    list_display  = ('product', 'location', 'quantity')
    list_filter   = ('location__warehouse', 'location')
    search_fields = ('product__name', 'location__name')
    raw_id_fields = ('product', 'location')




@admin.register(StockMoveLine)
class StockMoveLineAdmin(admin.ModelAdmin):
    list_display = ('move','product','quantity','product_uom' ,'source_location','dest_location','lot', 'created_at',)
    list_filter = ('move','source_location','dest_location','lot')
    search_fields = ('product__name',)



class StockMoveLineInline(admin.TabularInline):
    model = StockMoveLine
    extra = 0
    can_delete = False



@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display  = (
        'product', 'quantity', 'status',
        'source_location', 'dest_location', 'created_at',
    )
    list_filter   = ('status', 'source_location__warehouse')
    search_fields = ('product__name',)
    date_hierarchy = 'created_at'
    raw_id_fields = ('product', 'source_location', 'dest_location')
    readonly_fields = ('created_at',)

    inlines = (StockMoveLineInline,)



@admin.register(ProductsCategory)
class ProductsCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    list_filter = ('name',)



@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'name', 'expiration_date', 'manufacture_date')
    list_filter = ('product','name')
    search_fields = ('product__name','name', 'expiration_date', 'manufacture_date')

