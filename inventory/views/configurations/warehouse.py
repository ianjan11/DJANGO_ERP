import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from core.utils import htmx_error, htmx_success
from core.utils.format_errors import _format_form_errors
from inventory.forms.warehouse_form import WarehouseForm
from inventory.models import Warehouse


logger = logging.getLogger(__name__)


def warehouse_list(request):
    warehouses = Warehouse.objects.filter(
        active=True, company=request.company
    ).annotate(
        locations_count=Count(
            "locations", filter=Q(locations__active=True)
        )
    )

    context = {
        "warehouses": warehouses,
    }

    template = (
        "inventory/warehouse/partials/warehouse_list_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/warehouse_list.html"
    )

    return render(request, template, context)

@require_GET
def get_empty_warehouse_form(request):
    """Renders a blank WarehouseForm bound to the active user's company."""
    form = WarehouseForm(company=request.company)

    context = {
        "form": form,
    }

    template = (
        "inventory/warehouse/partials/warehouse_form_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/warehouse_form.html"
    )

    return render(request, template, context)

@login_required
def warehouse_detail(request, warehouse_id):
    warehouse = get_object_or_404(
        Warehouse,
        id=warehouse_id,
        company=request.company,
    )
    form = WarehouseForm(
        company=request.company,
        instance=warehouse,
    )

    context = {
        "warehouse": warehouse,
        "form": form,
    }

    template = (
        "inventory/warehouse/partials/warehouse_form_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/warehouse_form.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def edit_warehouse(request, warehouse_id):
    company = request.company
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"WarehouseFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            warehouse = get_object_or_404(
                Warehouse.objects.select_for_update(),
                id=warehouse_id,
                company=company,
            )

            # Fixed: Bound form with request.POST data
            form = WarehouseForm(
                data=request.POST,
                company=company,
                instance=warehouse,
            )

            if not form.is_valid():
                errors = _format_form_errors(form)
                return htmx_error(
                    request,
                    errors,
                    trigger={"WarehouseValidationError": {"errors": errors}},
                )

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"WarehouseValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during warehouse update")
        return htmx_error(
            request,
            "Failed to save warehouse due to an internal server error.",
            trigger={"WarehouseFailed": {"message": "Failed to save warehouse due to an internal error."}},
        )

    return htmx_success(
        request,
        "Warehouse updated successfully.",
        target="#inventory-display",
    )

@login_required
@require_POST
def create_warehouse(request):

    company = request.company
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
        )

    form = WarehouseForm(
        data=request.POST,
        company=company,
    )

    if not form.is_valid():
        return htmx_error(
            request,
            _format_form_errors(form),
        )

    try:
        with transaction.atomic():
            # Encapsulated in form.save() (sets company & derives company.partner)
            warehouse = form.save()
            redirect_url = reverse("inventory:warehouse_detail", args=[warehouse.id])

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error while creating warehouse")
        return htmx_error(
            request,
            "Failed to create warehouse due to an internal server error.",
        )

    return htmx_success(
        request,
        "Warehouse created successfully.",
        target="#inventory-display",

    )



