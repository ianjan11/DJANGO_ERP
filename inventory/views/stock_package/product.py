from django.views.decorators.http import require_POST
from pygments.lexers import data
from django.db import transaction
from django.urls import reverse
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from core.utils.format_errors import _format_form_errors
from inventory.services.stock.product_accounts import populate_product_accounts
from core.utils import htmx_error, htmx_success
from inventory.forms import ProductForm
import logging
from inventory.services.stock.load_product import load_product
from pygments.lexers import data
from django.db import transaction
from django.shortcuts import   get_object_or_404
from django.contrib.auth.decorators import  permission_required

from inventory.models import Product, StockLocation, Warehouse

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from inventory.forms.product_form import ProductForm

logger = logging.getLogger('django.request')

@login_required
@transaction.atomic
def product_detail_view(request,product_id):

    product = load_product(product_id, request)

    warehouses = Warehouse.objects.all()
    all_locations = StockLocation.objects.all()  # needed for destination dropdown
    form = ProductForm(company=request.company, instance=product)


    context = {
               'product':product,
               'warehouses': warehouses,
               'all_locations': all_locations,
               'form': form,

    }
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_details_partial.html', context)


    return render(request, 'inventory/stock/stock_details.html', context)


@login_required
def get_empty_product_form(request):
    form = ProductForm(company=request.company)

    context = {
        "form": form,
        "product": None,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_details_partial.html', context)

    return render(request, 'inventory/stock/stock_details.html', context)


@login_required
@transaction.atomic
@require_POST
def create_product_view(request):

    form = ProductForm(
     request.POST,
           company=request.company,)

    if not form.is_valid():
        return htmx_error(request, _format_form_errors(form))

    try:

        with transaction.atomic():
            product = form.save(commit=False)
            product.company = request.company
            populate_product_accounts(product)
            product.save()
            form.save_m2m()

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(request, errors)

    except Exception:
        logger.exception(
            "Unexpected error while creating product"
        )

        return htmx_error(
            request,
            "Failed to create product due to an internal server error.",
        )

    return htmx_success(
        request,
        message= "Successfully created product.",
        redirect_url= reverse(
            "inventory:stock_detail", args=[product.pk]
        )
    )


@require_POST
def edit_product_view(request, product_id):
    company = getattr(request, "company", None)
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"ProductFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            product = load_product(product_id, request, for_update=True)

            form = ProductForm(
                request.POST,
                instance=product,
                company=company,
            )


            if not form.is_valid():
                errors = _format_form_errors(form)
                return htmx_error(
                    request,
                    errors,
                    trigger={"ProductValidationError": {"errors": errors}},
                )

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"ProductValidationError": {"errors": errors}},

        )

    except Exception:
        logger.exception("Unexpected error occurred during product update")
        return htmx_error(
            request,
            "Failed to save product due to an internal server error.",
            trigger={"paymentFailed": {"message": "Failed to save product due to an internal error."}},
        )

    return htmx_success(
        request,
        "Product updated successfully.",
        trigger={"ProductSuccess": {"message": "Product updated successfully."}},
        target="#invetory-display",
    )


