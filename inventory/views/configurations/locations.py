import logging
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from core.utils import htmx_error, htmx_success
from core.utils.format_errors import _format_form_errors
from inventory.forms.stocklocation_form import StockLocationForm
from inventory.models import  StockLocation

logger = logging.getLogger(__name__)


@login_required
@require_GET
def locations_list(request):
    locations = StockLocation.objects.filter(company=request.company)

    paginator = Paginator(locations, 10)
    page = request.GET.get('page')
    paged_locations = paginator.get_page(page)

    context = {
        "locations": paged_locations,
    }

    template = (
        "inventory/warehouse/partials/locations_list_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/locations_list.html"
    )

    return render(request, template, context)


@login_required
@require_GET
def get_empty_location_form(request):
    """Renders a blank StockLocationForm bound to the active user's company."""
    form = StockLocationForm(company=request.company)

    context = {
        "form": form,
    }

    template = (
        "inventory/warehouse/partials/location_form_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/location_form.html"
    )

    return render(request, template, context)


@login_required
@require_GET
def location_detail(request, location_id):
    location = get_object_or_404(
        StockLocation,
        id=location_id,
        company=request.company,
    )
    form = StockLocationForm(
        company=request.company,
        instance=location,
    )

    context = {
        "location": location,
        "form": form,
    }

    template = (
        "inventory/warehouse/partials/location_form_partial.html"
        if request.headers.get("HX-Request")
        else "inventory/warehouse/location_form.html"
    )

    return render(request, template, context)


@login_required
@require_POST
def create_location(request):


    company = request.company
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
        )

    form = StockLocationForm(
        data=request.POST,
        company=company,
    )

    if not form.is_valid():
        errors = _format_form_errors(form)
        return htmx_error(
            request,
            errors,
            trigger={"LocationValidationError": {"errors": errors}},
        )

    try:
        with transaction.atomic():
            # Fixed: variable named location instead of warehouse
            location = form.save()
            redirect_url = reverse("inventory:location_detail", args=[location.id])

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error while creating location")
        return htmx_error(
            request,
            "Failed to create location due to an internal server error.",
        )

    return htmx_success(
        request,
        "Location created successfully.",
        redirect_url=redirect_url,
        trigger={"LocationCreated": {"message": "Location created successfully."}},
    )


@login_required
@require_POST
def edit_location(request, location_id):
    company = request.company
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"LocationFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            location = get_object_or_404(
                StockLocation.objects.select_for_update(),
                id=location_id,
                company=company,
            )

            form = StockLocationForm(
                data=request.POST,
                company=company,
                instance=location,
            )

            if not form.is_valid():
                errors = _format_form_errors(form)
                return htmx_error(
                    request,
                    errors,
                    trigger={"LocationValidationError": {"errors": errors}},
                )

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"LocationValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during location update")
        return htmx_error(
            request,
            "Failed to save location due to an internal server error.",
            trigger={"LocationFailed": {"message": "Failed to save location due to an internal error."}},
        )

    return htmx_success(
        request,
        "Location updated successfully.",
        trigger={"LocationUpdated": {"message": "Location updated successfully."}},
        target="#inventory-display",
    )


