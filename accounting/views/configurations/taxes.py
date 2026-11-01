import logging
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounting.forms.tax_form import TaxForm
from accounting.models import Tax
from accounting.services.tax_service.tax_loader import load_tax
from core.utils import htmx_success, htmx_error


logger = logging.getLogger("accounting.tax")


def _build_context(request):
    company = request.company

    taxes = (
        Tax.objects
        .filter(company=company)
        .select_related("tax_group")
        .order_by("sequence", "id")
    )

    search_tax = request.GET.get("search_tax")

    if search_tax:
        taxes = taxes.filter(
            Q(name__icontains=search_tax)
            | Q(type_tax_use__icontains=search_tax)
            | Q(computation__icontains=search_tax)
        )

    paginator = Paginator(taxes, 10)

    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return {
        "taxes": page_obj,
    }

@login_required
def taxes_view(request):
    context = _build_context(request)

    template = (
        "accounting/configurations/taxes/partials/taxes_list_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/taxes/taxes_list.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def toggle_tax_view(request, tax_id):
    try:
        with transaction.atomic():
            tax = load_tax(
                tax_id,
                request=request,
                for_update=True,
            )

            tax.is_active = not tax.is_active

            tax.save(
                update_fields=["is_active"],
            )

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(
            request,
            errors,
            trigger={
                "TaxValidationError": {
                    "errors": errors,
                }
            },
        )

    except Exception:
        logger.exception(
            "Unexpected error while toggling tax status"
        )

        return htmx_error(
            request,
            "Failed to update tax status due to an internal server error.",
        )

    return htmx_success(
        request,
        "Tax status updated.",
        trigger={
            "TaxUpdated": {
                "message": "Tax status updated successfully.",
            }
        },
    )

@login_required
def tax_detail(request, tax_id):
    tax = load_tax(
        tax_id,
        request,
    )

    form = TaxForm(
        company=request.company,
        instance=tax,
    )

    context = {
        "tax": tax,
        "form": form,
    }

    template = (
        "accounting/configurations/taxes/partials/tax_detail_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/taxes/tax_detail.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def edit_tax(request, tax_id):
    company = getattr(request.user, "company", None)

    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={
                "TaxFailed": {
                    "message": "User has no company assigned.",
                }
            },
        )

    try:
        with transaction.atomic():
            tax = load_tax(
                tax_id,
                request=request,
                for_update=True,
            )

            form = TaxForm(
                request.POST,
                company=company,
                instance=tax,
            )

            if not form.is_valid():
                errors = {
                    field: [str(error) for error in error_list]
                    for field, error_list in form.errors.items()
                }

                return htmx_error(
                    request,
                    errors,
                    trigger={
                        "TaxValidationError": {
                            "errors": errors,
                        }
                    },
                )

            form.save()

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(
            request,
            errors,
            trigger={
                "TaxValidationError": {
                    "errors": errors,
                }
            },
        )

    except Exception:
        logger.exception(
            "Unexpected error while updating tax"
        )

        return htmx_error(
            request,
            "Failed to save tax due to an internal server error.",
        )

    return htmx_success(
        request,
        "Tax updated successfully.",
        trigger={
            "TaxSuccess": {
                "message": "Tax updated successfully.",
            }
        },
        target="#accounting-display",
    )

@login_required
def get_empty_tax_form(request):
    form = TaxForm(
        company=request.company,
    )

    context = {
        "form": form,
        "tax": None,
    }

    template = (
        "accounting/configurations/taxes/partials/tax_form_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/taxes/tax_form.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def create_tax(request):

    company = getattr(request.user, "company", None)

    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
        )

    form = TaxForm(
        request.POST,
        company=company,
    )

    if not form.is_valid():
        errors = {
            field: [str(error) for error in error_list]
            for field, error_list in form.errors.items()
        }

        return htmx_error(
            request,
            errors,
            trigger={
                "TaxValidationError": {
                    "errors": errors,
                }
            },
        )

    try:
        with transaction.atomic():
            tax = form.save()

            redirect_url = reverse(
                "accounting:tax_detail",
                args=[tax.id],
            )

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(
            request,
            errors,
        )

    except Exception:
        logger.exception(
            "Unexpected error while creating tax"
        )

        return htmx_error(
            request,
            "Failed to create tax due to an internal server error.",
        )

    return htmx_success(
        request,
        "Tax created successfully.",
        redirect_url=redirect_url,
    )


@login_required
@require_POST
def delete_tax(request):
    tax_ids = request.POST.getlist("tax_ids")


    # Empty selection
    if not tax_ids:
        return htmx_error(
            request,
            "No taxes were selected for deletion.",
        )

    try:
        with transaction.atomic():
            taxes_qs = (
                Tax.objects
                .filter(
                    id__in=tax_ids,
                    company=request.company,
                )
                .select_for_update()
            )

            count = taxes_qs.count()

            if count == 0:
                return htmx_error(
                    request,
                    "Selected taxes were not found or access denied.",
                )

            for tax in taxes_qs:
                tax.delete()

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(
            request,
            errors,
        )

    except Exception:
        logger.exception(
            "Unexpected error occurred during tax deletion"
        )

        return htmx_error(
            request,
            "Failed to delete tax(s) due to an internal server error.",
        )

    return htmx_success(
        request,
        "Tax(s) deleted successfully.",
        trigger={
            "TaxSuccess": {
                "message": "Tax deleted successfully.",
            }
        },
    )