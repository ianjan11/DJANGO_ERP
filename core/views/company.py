import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms.company_form import CompanyForm
from core.models import Company
from core.utils import htmx_error, htmx_success
from users.models import CompanyMembership

logger = logging.getLogger(__name__)

@login_required
def company_list(request):
    companies = Company.objects.all()

    context = {
        'companies': companies
    }

    template = (
        "core/settings/company/partials/company_list_partial.html"
        if request.headers.get("HX-Request")
        else "core/settings/company/company_list.html"

    )
    return render(request, template, context)


@login_required
def get_empty_company_form(request):
    company_form = CompanyForm(user=request.user)

    context = {
        'company_form': company_form,
        "form_context": "settings",
        "back_url": reverse("core:company_list"),

    }

    template = (
        "core/settings/company/partials/company_detail_partial.html"
        if request.headers.get("HX-Request")
        else "core/settings/company/company_detail.html"

    )

    return render(request, template, context)


@login_required
def company_details(request, company_id):

    membership = CompanyMembership.objects.filter(
        user=request.user,
        company_id=company_id,
        is_active=True,).first()


    if not membership:
       return htmx_error(
           request,
           "You are not authorized to view this company.",
       )

    company = membership.company

    company_form = CompanyForm(
        instance=company,
        user=request.user,
    )

    context = {
        'company_form': company_form,
        'form_context': "settings",
        "back_url": reverse("core:company_list"),
    }


    template = (
        "core/settings/company/partials/company_detail_partial.html"
        if request.headers.get("HX-Request")
        else "core/settings/company/company_detail.html"
    )

    return render(request, template, context)


@login_required
@require_POST
def company_create_view(request):

    form = CompanyForm(request.POST, user=request.user)

    if not form.is_valid():
        return htmx_error(
            request,
            {
                field: [str(error) for error in errors]
                for field, errors in form.errors.items()
            },
        )

    try:
      with transaction.atomic():
        company = form.save()

        if request.session.get("active_company_id"):
            redirect_url = reverse(
                "core:company_details",
                args=[company.id],
            )
        else:
            redirect_url = reverse(
                "users:select-company",
            )

        return htmx_success(
            request,
            "Company successfully created.",
            redirect_url=redirect_url,
        )

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(request, errors)

    except Exception:
        logger.exception(
            "Unexpected error while creating company"
        )

        return htmx_error(
            request,
            "Failed to create company due to an internal server error.",
        )


@login_required
@require_POST
def company_edit_view(request, company_id):


    company = get_object_or_404(Company, pk=company_id)

    # Pass the instance directly to the form
    form = CompanyForm(request.POST, instance=company, user=request.user)

    if not form.is_valid():
        return htmx_error(
            request,
            {f: [str(e) for e in errs] for f, errs in form.errors.items()},
        )

    try:
        company = form.save()
        redirect_url = reverse("core:company_details", args=[company.id])

        return htmx_success(
            request,
            "Company successfully updated.",
            redirect_url=redirect_url,
        )

    except ValidationError as e:
        errors = (
            e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        )
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error while updating company %s", company_id)
        return htmx_error(
            request,
            "Failed to update company due to an internal server error.",
        )




