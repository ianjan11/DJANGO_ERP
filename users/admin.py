from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

from users.models import UserProfile, CompanyMembership

User = get_user_model()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "date_joined",
    )

    list_filter = (
        "is_staff",
        "is_active",
        "date_joined",
    )

    search_fields = (
        "email",
        "first_name",
        "last_name",
    )

    ordering = ("email",)

    fieldsets = (
        (None, {
            "fields": ("email", "password"),
        }),
        ("Personal Information", {
            "fields": (
                "first_name",
                "last_name",
            ),
        }),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        }),
        ("Important Dates", {
            "fields": (
                "last_login",
                "date_joined",
            ),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "password1",
                "password2",
                "is_active",
                "is_staff",
            ),
        }),
    )


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "company",
        "is_active",
    )

    list_filter = (
        "company",
        "is_active",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "company__name",
    )

    autocomplete_fields = (
        "user",
        "company",
    )

    ordering = (
        "company",
        "user__email",
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "default_location",
        "default_payment_term",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    list_filter = (
        "default_location",
        "default_payment_term",
    )

    autocomplete_fields = (
        "user",
    )