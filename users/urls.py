from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views
from users.views.login_view import CustomLoginView
from users.views.select_company_view import SelectCompanyView, select_company
from users.views.auth_view import check_auth

app_name = 'users'


urlpatterns = [
    path("home/", views.home, name="home"),

    #registration
    path(
        "register/",
        views.public_register_view,
        name="register",
    ),




    # Authentication
    path(
        "login/",
        CustomLoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
    path(
        "check-auth/",
        check_auth,
        name="check_auth",
    ),

    # Company context
    path(
        "user/select-company/",
        SelectCompanyView.as_view(),
        name="select-company",
    ),
    path(
        "user/create-company/",
        views.create_first_company,
        name="create-first-company",
    ),

    path(
        "user/select-company/set/",
        select_company,
        name="select-company-set",
    ),



]