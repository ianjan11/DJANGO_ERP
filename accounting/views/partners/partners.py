from django.db import transaction, IntegrityError
from django.db.models import   Q
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from prompt_toolkit.validation import ValidationError

from accounting.forms.partner_form import PartnerForm
from core.models import Partner
from core.utils import htmx_error, htmx_success
import logging

logger = logging.getLogger('sales.invoice')

@login_required
def get_customers_view(request):
    return get_partners(request, 'CUSTOMER')


@login_required
def get_vendors_view(request):
    return get_partners(request, 'VENDOR')


def get_partners(request, partner_type):
    # 1. Base Query: Filter active partners for user's company
    # Includes partners designated as BOTH alongside the requested type
    partners = (
        Partner.objects.filter(
            partner_type__in=[partner_type, 'BOTH'],
            company=request.company,
            is_active=True,
        )
        .select_related(
            'payment_term',
            'supplier_payment_term',
            'account_receivable',
            'account_payable',
            'preferred_purchase_currency',
        )
        .order_by('name')
    )

    # 2. Search Filter (matches name, email, phone, or tax_id)
    search_query = request.GET.get('search_partner', '').strip()
    if search_query:
        partners = partners.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(tax_id__icontains=search_query)
        )

    # 3. Build Context
    context = _build_context(request, partners, partner_type)

    # 4. Render Partial vs full Page
    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/partners/partials/partners_table.html",
            context,
        )

    return render(
        request,
        "accounting/partners/partners_list.html",
        context,
    )


def _build_context(request, partners, partner_type):

    paginator = Paginator(partners, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    form = PartnerForm(request.POST, company=request.company)


    return {
        "summary": {
            "total_count": paginator.count,
        },
        "partners": page_obj,
        "form": form,
    }


@require_POST
def create_partner_view(request):
    form = PartnerForm(request.POST, company=request.company)
    form.instance.company = request.company

    if not form.is_valid():
        return htmx_error(
            request,
            form.errors,
            trigger={"PartnerFormValidationError": {"errors": form.errors}},
        )

    try:
        with transaction.atomic():
            partner = form.save()
            detail_url = reverse("accounting:partner_detail", kwargs={"partner_id": partner.id})

    except IntegrityError:
        # Caught when unique constraint is violated at the DB level
        errors = {"__all__": ["A partner with this name or Tax ID already exists."]}
        return htmx_error(
            request,
            errors,
            trigger={"PartnerDuplicateError": {"errors": errors}},
        )

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"PartnerValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during partner creation")
        return htmx_error(
            request,
            "Failed to create partner. An internal error occurred.",
            trigger={"PartnerServerError": {"message": "Failed to create partner"}},
        )

    return htmx_success(
        request,
        "Partner Created Successfully.",
        trigger={"PartnerCreatedSuccess": {"message": "Partner Created successfully"}},
        redirect_url=detail_url,
    )





