import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounting.models import PaymentTerm
from core.utils import htmx_error, htmx_success
from core.utils.format_errors import _format_form_errors
from inventory.models import Warehouse
from users.forms.profile_and_membership_form import UserProfileForm, CompanyMembershipForm
from users.forms.register_form import UserSignUpForm
from users.models import CompanyMembership, UserProfile

logger = logging.getLogger(__name__)


def _require_company(request):
    company = getattr(request, "company", None)
    if not company:
        raise PermissionDenied("Action restricted: No active tenant company found.")
    return company


@login_required
def tenants_list_view(request):
    company = _require_company(request)

    members = (
        CompanyMembership.objects
        .filter(company=company, is_active=True)
        .select_related("user")
        .order_by("user__email", "pk")
    )

    search_member = request.GET.get("search_member")
    if search_member:
        members = members.filter(
            Q(user__first_name__icontains=search_member)
            | Q(user__email__icontains=search_member) |
            Q(user__last_name__icontains=search_member)
        )

    page_obj = Paginator(members, 10).get_page(request.GET.get("page"))
    context = {"members": page_obj}

    if request.headers.get("HX-Request"):
        return render(request, "core/settings/tenants/partials/tenants_list_partial.html", context)
    return render(request, "core/settings/tenants/tenants_list.html", context)


@login_required
def get_tenant_form(request):
    _require_company(request)

    context = {
        "form": UserSignUpForm(),
        "form_context": "settings",
        "back_url": reverse("core:tenant_user_list"),
    }

    if request.headers.get("HX-Request"):
        return render(request, "core/settings/tenants/partials/tenant_form_partial.html", context)
    return render(request, "core/settings/tenants/tenant_form.html", context)


@login_required
def tenant_details(request, membership_id):
    """Show one member of the active company. URL conf must pass `membership_id`."""
    company = _require_company(request)

    membership = get_object_or_404(
        CompanyMembership.objects.select_related("user"),
        pk=membership_id,
        company=company,
    )
    profile = UserProfile.objects.filter(user=membership.user).first()

    profile_form = UserProfileForm(instance=profile, company=company)
    membership_form = CompanyMembershipForm(instance=membership, user=membership.user)


    context = {
        "membership": membership,
        "tenant": profile,
        "profile_form": profile_form,
        "membership_form": membership_form,
        "form_context": "settings",
        "back_url": reverse("core:tenant_user_list"),
    }

    if request.headers.get("HX-Request"):
        return render(request, "core/settings/tenants/partials/tenant_detail_partial.html", context)
    return render(request, "core/settings/tenants/tenant_detail.html", context)


@login_required
@require_POST
def tenant_create_view(request):
    """Admin creates a user within their active company context."""
    company = _require_company(request)

    form = UserSignUpForm(request.POST)
    if not form.is_valid():
        return htmx_error(request, _format_form_errors(form))

    try:
        with transaction.atomic():
            user = form.save()

            default_warehouse = Warehouse.objects.filter(
                company=company, active=True
            ).first()

            default_payment_term = PaymentTerm.objects.filter(
                company=company
            ).first()

            UserProfile.objects.create(
                user=user,
                default_location=default_warehouse,
                default_currency=company.currency,
                default_payment_term= default_payment_term,
            )

            membership = CompanyMembership.objects.create(
                company=company, user=user, is_active=True
            )

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error while creating user")
        return htmx_error(
            request,
            "Failed to create user due to an internal server error.",
        )

    messages.success(request, "User created successfully.")

    return htmx_success(
        request,
        message="User created successfully.",
        redirect_url=reverse("core:tenant_user_detail", args=[membership.id]),
    )


@login_required
@require_POST
def user_profile_update(request, membership_id):
    # 1. Fetch the specific membership and its associated user profile within the active company
    company = getattr(request, "company", None)
    if not company:
        raise PermissionDenied("No active tenant company found.")


    membership = get_object_or_404(
        CompanyMembership,
        id=membership_id,
        company=company
    )

    # Get the user's profile (create one if it doesn't exist yet)
    profile, _ = UserProfile.objects.get_or_create(user=membership.user)

    # 2. Bind the POST data to the existing model instances
    profile_form = UserProfileForm(request.POST, instance=profile, company=company)
    membership_form = CompanyMembershipForm(request.POST, instance=membership, user=membership.user)

    if not profile_form.is_valid() or not membership_form.is_valid():
        # Combine or return errors from both forms gracefully
        errors = {}
        if not profile_form.is_valid():
            errors.update(_format_form_errors(profile_form))
        if not membership_form.is_valid():
            errors.update(_format_form_errors(membership_form))
        return htmx_error(request, errors)

    try:
        with transaction.atomic():
            profile_form.save()
            membership_form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error while updating user profile")
        return htmx_error(
            request,
            "Failed to update user profile and membership due to an internal server error.",
        )

    return htmx_success(
        request,
        message="User updated successfully.",

    )
