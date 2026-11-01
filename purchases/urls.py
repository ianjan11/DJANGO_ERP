from django.urls import path
from . import views

app_name = 'purchases'
urlpatterns = [

#------------------------------------------ purchase Urls------------------------------------------------#

   path('purchases/dashboard/', views.purchases_dashboard, name='purchases_dashboard'),
   path("purchases/create/", views.purchase_create_or_detail, name="purchase_create_or_detail"),
   path("purchases/<int:purchase_id>/", views.purchase_create_or_detail, name="purchase_create_or_detail"),

   path('purchases/', views.purchases_list, name='purchases_list'),
   path('purchases/update/', views.purchase_update, name='purchase_update'),
   path('purchases/<int:purchase_id>/confirm/', views.confirm_purchase, name='confirm_purchase'),
   path('purchases/<int:purchase_id>/delete/', views.delete_purchase, name='delete_purchase'),
   path('purchases/<int:purchase_id>/cancel/', views.cancel_purchase, name='cancel_purchase'),
   path('purchases/<int:purchase_id>/send/', views.send_purchase, name='send_purchase'),
   path('purchases/<int:purchase_id>/approve/', views.approve_purchase, name='approve_purchase'),
   path('purchases/<int:purchase_id>/reset/', views.reset_purchase, name='reset_purchase'),

   path('purchases/<int:purchase_id>/item-rows/', views.purchase_line_row, name='purchase_item_row'),
   path('purchases/<int:purchase_id>/totals/', views.purchase_totals, name='purchases_totals'),

   path("purchases/<int:purchase_id>/to-invoice/",views.purchase_to_invoice_view,name="purchase_to_invoice",),

]

