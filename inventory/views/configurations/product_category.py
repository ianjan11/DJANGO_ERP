from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
import logging
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from core.utils import htmx_error, htmx_success
from inventory.models import ProductsCategory
from inventory.services.stock.category_accounts import populate_category_accounts
logger = logging.getLogger(__name__)
from core.utils.format_errors import _format_form_errors
from inventory.forms.product_form import  ProductsCategoryForm



def _validation_errors(e):
    return e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}


def _refresh_descendant_names(category):
    """complete_name is stored, so children go stale when a parent is renamed or moved."""
    for child in category.children.all():
        child.save()  # save() recomputes complete_name from the (already saved) parent
        _refresh_descendant_names(child)



@login_required
def get_empty_category_form(request):
    form = ProductsCategoryForm(company=request.company)

    context = {
        "form": form,
        "category": None,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/categories/partials/category_details_partial.html', context)


    return render(request, 'inventory/categories/category_details.html', context)



# ---------------- create ----------------
@login_required
@require_POST
def create_category_view(request):
    company = getattr(request, "company", None)
    if not company:
        return htmx_error(request, "User has no company assigned.")

    form = ProductsCategoryForm(request.POST, company=company)

    if not form.is_valid():
        return htmx_error(request, _format_form_errors(form))

    try:
        with transaction.atomic():
            category = form.save(commit=False)
            category.company = company
            populate_category_accounts(category)   # fill blanks, once, on creation
            category.save()

    except ValidationError as e:
        return htmx_error(request, _validation_errors(e))

    except Exception:
        logger.exception("Unexpected error while creating category")
        return htmx_error(request, "Failed to create category due to an internal server error.")

    return htmx_success(
        request,
        message="Successfully created category.",
    )

# ---------------- edit ----------------
@login_required
@require_POST
def edit_category_view(request, category_id):
    company = getattr(request, "company", None)
    if not company:
        return htmx_error(request, "User has no company assigned.")

    try:
        with transaction.atomic():
            category = get_object_or_404(
                ProductsCategory.objects.select_for_update(),
                pk=category_id,
                company=company,
            )

            form = ProductsCategoryForm(request.POST, instance=category, company=company)

            if not form.is_valid():
                return htmx_error(request, _format_form_errors(form))

            # No populate here: clearing an account on edit is how a user
            # opts back into inheriting from the parent / company default.
            category = form.save()

            if {"name", "parent"} & set(form.changed_data):
                _refresh_descendant_names(category)

    except ValidationError as e:
        return htmx_error(request, _validation_errors(e))

    except Exception:
        logger.exception("Unexpected error while updating category %s", category_id)
        return htmx_error(request, "Failed to save category due to an internal server error.")

    return htmx_success(
        request,
        "Category updated successfully.",
        target="#invetory-display",
    )


@login_required
def categories_view(request):

    categories = ProductsCategory.objects.all().filter(company=request.company).order_by('-name')

    search_category = request.GET.get('search_category')

    if search_category:
        categories = categories.filter(
            Q (name__icontains=search_category)
        )


    paginator = Paginator(categories, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)


    context = {
        'categories': page_obj,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'inventory/categories/partials/categories_partial.html', context)


    return render(request, 'inventory/categories/categories.html', context)



@login_required
@transaction.atomic
def category_detail_view(request,category_id):

    category = get_object_or_404(ProductsCategory, pk=category_id)

    form = ProductsCategoryForm(company=request.company, instance=category)

    context = {
               'category':category,
               'form': form,

    }
    if request.headers.get('HX-Request'):
        return render(request, 'inventory/categories/partials/category_details_partial.html', context)


    return render(request, 'inventory/categories/category_details.html', context)

