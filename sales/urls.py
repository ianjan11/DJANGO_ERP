from django.urls import path
from . import views

app_name = 'sales'
urlpatterns = [

   path('sales/dashboard/', views.sales_dashboard, name='sales_dashboard'),
   path('sales/orders', views.sales_orders_list, name='sales_orders_list'),
   path('sales/order/update/',views.sales_order_update, name='sales_order_update'),
   path('sales/order/<int:order_id>/totals/', views.sales_order_totals, name='sales_order_totals'),
   path('sales/order/create/',views.sales_order_create_or_detail,name='sales_order_create'),
   path('sales/order/<int:order_id>/item-rows/', views.sales_order_item_row, name='sales_order_item_row'),
   path('sales/orders/<int:order_id>/cancel', views.cancel_order_view, name='cancel_order'),

   path('sales/order/<int:order_id>/reset/', views.reset_order_view, name='reset_sales_order'),

   path('sales/order/refresh/<int:order_id>/', views.refresh_order, name='order_refresh'),
   path('sales/order/<int:order_id>/delete/', views.delete_order_view, name='order_delete'),

   path('sales/order/<int:order_id>/',views.sales_order_create_or_detail,name='sales_order_create_or_detail'),

   path('sales/order/<int:order_id>/confirm/', views.confirm_order_view, name='confirm_sales_order'),
   path('sales/order/<int:order_id>/send/', views.send_order_view, name='send_sales_order'),

   path("sales/<int:order_id>/to-invoice/", views.sales_to_invoice_view,name="sales_to_invoice", ),


]

