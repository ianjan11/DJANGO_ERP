from django.urls import path
from . import views

app_name = 'core'
urlpatterns = [

    path( "settings/", views.settings_view, name="settings", ),
    path("settings/company/list/", views.company_list, name="company_list", ),
    path("settings/company/new/", views.get_empty_company_form, name="get_company_form", ),
    path("settings/company/<int:company_id>/", views.company_details, name="company_details", ),
    path("settings/company/create/", views.company_create_view, name="company_create", ),
    path("settings/company/<int:company_id>/edit/", views.company_edit_view, name="company_edit", ),

    path("settings/users/", views.tenants_list_view, name="tenant_user_list", ),
    path("settings/users/<int:membership_id>/", views.tenant_details, name="tenant_user_detail", ),
    path("settings/users/new/", views.get_tenant_form, name="get_tenant_form", ),
    path("settings/users/create/", views.tenant_create_view, name="tenant_user_create", ),
    path("settings/users/<int:membership_id>/update/", views.user_profile_update, name="user_profile_update", ),

    path('partners/customers/', views.get_customers_view, name='customers'),
    path('partners/vendors/', views.get_vendors_view, name='vendors'),
    path('partners/list/', views.get_all_partners, name='partners'),

    path('partner/new/', views.get_empty_partner_form, name='get_partner_form', ),
    path('partner/create/', views.create_partner_view, name='partner_create'),
    path('accounting/partner/<int:partner_id>/', views.partners_details_view, name='partner_detail'),
    path('accounting/partner/<int:partner_id>/edit', views.edit_partner_view, name='partner_edit'),

]

