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

]

