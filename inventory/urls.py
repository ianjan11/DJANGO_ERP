from django.urls import path
from . import views

app_name = 'inventory'
urlpatterns = [

   path('inventory/dashboard/', views.inventory_dashboard, name='inventory_dashboard'),

   path("inventory/pickings/", views.get_pickings, name="get_pickings"),

   path("inventory/receipts/", views.receipts_view, name="receipt_list"),
    path("inventory/deliveries/", views.deliveries_view, name="delivery_list"),
    path("inventory/returns/", views.returns_view, name="return_list"),
    path("inventory/transfers/", views.internal_transfers_view, name="internal_transfer_list"),

   path('inventory/picking/<int:picking_id>/', views.picking_create_or_detail_view, name='picking_detail'),
   path('inventory/picking/create/', views.picking_create_or_detail_view, name='picking_create'),

   path('inventory/picking/<int:picking_id>/confirm/', views.confirm_picking_view, name='picking_confirm'),
   path('inventory/picking/<int:picking_id>/assign/', views.assign_picking_view, name='picking_assign'),
   path('inventory/picking/<int:picking_id>/validate/', views.validate_picking_view, name='picking_validate'),
   path('inventory/picking/<int:picking_id>/cancel/', views.cancel_picking_view, name='picking_cancel'),
   path("inventory/pickings/<int:picking_id>/operations/",views.stock_move_operations,name="stock_move_operations",),
   path("inventory/pickings/<int:picking_id>/item-row/", views.picking_item_row, name="picking_item_row", ),
   path('inventory/picking/updates/', views.picking_update, name='picking_update'),
   path("inventory/pickings/<int:picking_id>/next/", views.get_next_picking_view, name="get_next_picking"),
   path("inventory/pickings/<int:picking_id>/previous/", views.get_previous_picking_view, name="get_previous_picking"),
   path("inventory/pickings/<int:picking_id>/return/", views.issue_return_view, name="issue_return"),

   path('inventory/stock/', views.stock_view, name='view_stock'),

   path('inventory/product/new/', views.get_empty_product_form, name='new_product'),
   path('inventory/product/create/', views.create_product_view, name='create_product'),
   path('inventory/product/<int:product_id>/edit/', views.edit_product_view, name='edit_product'),

   path('inventory/configurations/categories/', views.categories_view, name='view_categories'),
   path('inventory/configurations/category/<int:category_id>/', views.category_detail_view, name='category_detail'),
   path('inventory/configurations/product-category/', views.get_empty_category_form, name='new_category'),
   path('inventory/category/create', views.create_category_view, name='create_category'),
   path('inventory/category/<int:category_id>/edit/', views.edit_category_view, name='edit_category'),

   path('inventory/product/<int:product_id>/', views.product_detail_view, name='stock_detail'),
   path('inventory/<int:product_id>/info', views.stock_info, name='stock_info'),
   path('inventory/<int:product_id>/adjustments/price/', views.product_price_change_view, name='price_adjustments'),
   path('inventory/<int:product_id>/price_changes/', views.product_price_changes, name='price_changes'),
   path('inventory/product-sales-chart/<int:product_id>/', views.product_movement_chart_per_month, name='product_sales_chart'),
   path('inventory/trend-chart/<int:product_id>/', views.product_movement_trend, name='product_trend'),
   path('inventory/<int:product_id>/history', views.stock_move_history, name='movement_history'),
   path("inventory/warehouses/<int:warehouse_id>/locations/", views.get_locations_by_warehouse,
        name='get_locations_by_warehouse'),
   path("inventory/product/<int:product_id>/locations/", views.get_product_stock_by_location,
        name="get_product_stock_by_location"),
   path('inventory/charts/', views.stock_view_charts, name='stock_charts'),


   path("inventory/configurations/warehouse/", views.warehouse_list, name="warehouse_list"),
   path("inventory/configurations/warehouse/new/", views.get_empty_warehouse_form, name="warehouse_create_form"),
   path("inventory/configurations/warehouses/<int:warehouse_id>/",views.warehouse_detail,name="warehouse_detail",),
   path("inventory/configurations/warehouses/<int:warehouse_id>/edit/",views.edit_warehouse,name="warehouse_edit",),
   path( "inventory/configurations/warehouses/create/",views.create_warehouse,name="warehouse_create",),


   path("inventory/configurations/locations/",views.locations_list,name="locations_list",),
   path("inventory/configurations/locations/create/",views.create_location,name="create_location",),
   path( "inventory/configurations/locations/new/",views.get_empty_location_form,name="get_empty_location_form",),
   path("inventory/configurations/locations/<int:location_id>/",views.location_detail,name="location_detail",),
   path("inventory/configurations/locations/<int:location_id>/edit/",views.edit_location,name="edit_location",),

   path("inventory/physical_inventory/", views.physical_inventory_views, name="physical_inventory"),
   path("inventory/physical_inventory/<int:quant_id>/adjustment/", views.stock_adjust_view, name="stock_adjustment"),
   path("inventory/physical_inventory/relocation/", views.stock_relocate_view, name="stock_relocation"),

]

