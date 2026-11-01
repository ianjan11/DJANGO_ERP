from pygments.lexers import data
from django.db import transaction
from django.contrib.auth.decorators import login_required, permission_required
from inventory.forms import ProductPriceForm
from inventory.models import ProductPrice
import json

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from pygments.lexers import data
import logging
from core.utils import htmx_error
from inventory.models import Product
from django.core.exceptions import ValidationError

logger = logging.getLogger('sales.invoice')



def product_price_change_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)


    context = {
        'product': product,
    }
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/stock/partials/stock_components/revalue_cost.html', context)

    return render(request, 'inventory/stock/stock_details.html', context)



@require_POST
@login_required
@transaction.atomic
def product_price_changes(request, product_id):
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    form = ProductPriceForm(request.POST)

    if not form.is_valid():
        errors = {
            field: [str(e) for e in error_list]
            for field, error_list in form.errors.items()
        }
        return htmx_error(request, errors)

    data = form.cleaned_data

    try:
        price_change, created = ProductPrice.objects.update_or_create(
            product=product,
            start_date=data['start_date'],  # lookup field
            defaults={
                'price': data['price'],
                'product_cost': data['product_cost'],
                'end_date': data['end_date'],
            },
        )

        context = {
            'product': product,
        }

        response = render(request, 'inventory/stock/partials/stock_components/revalue_cost.html', context)

        response["HX-Trigger"] = json.dumps({
            "showNotification": {
                "message": "Price updated successfully." if not created else "Price added successfully.",
                "level": "success",
            }
        })
        return response

    except ValidationError as e:
        errors = e.messages if hasattr(e, "messages") else [str(e)]
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Price change failed for product %s", product_id)
        return htmx_error(request, ["Something went wrong while updating the price."])

