from .pickings.picking import  (deliveries_view, returns_view, receipts_view,
                                internal_transfers_view, get_pickings)
from .pickings.picking_details import (picking_create_or_detail_view, cancel_picking_view,
                                       confirm_picking_view, picking_item_row,
                                       picking_update, assign_picking_view,
                                       validate_picking_view, get_next_picking_view, get_previous_picking_view)

from inventory.views.stock_package.product import (create_product_view, edit_product_view,
                                                   get_empty_product_form,product_detail_view)
from .product_per_location import get_locations_by_warehouse,get_product_stock_by_location
from inventory.views.stock_package.stock import stock_view
from .charts import stock_view_charts
from .stock_package.product_trend import product_movement_chart_per_month, product_movement_trend
from .invetory_dashboard import inventory_dashboard
from .stock_package.on_hand import stock_info
from .stock_package.Price_adjustments import product_price_changes, product_price_change_view
from .stock_package.stock_move_history import stock_move_history
from inventory.views.configurations.warehouse import warehouse_list, get_empty_warehouse_form, warehouse_detail, create_warehouse, edit_warehouse
from inventory.views.configurations.locations import location_detail,locations_list,create_location,get_empty_location_form, edit_location
from .stock_moves.stock_move_operations import stock_move_operations
from inventory.views.stock_package.physical_inventory import physical_inventory_views
from .stock_package.transfers_and_adjustments import stock_relocate_view, stock_adjust_view
from .pickings.returns import issue_return_view
from .configurations.product_category import (get_empty_category_form, edit_category_view,
                                              create_category_view, categories_view, category_detail_view)