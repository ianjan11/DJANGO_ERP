import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.forms.partner_form import PartnerForm
from core.models import Partner
from core.utils import htmx_error, htmx_success
from core.utils.module import _module, _render, _validation_errors

logger = logging.getLogger(__name__)


# Back-link targets. Accepts both the ?source= style ("customers") and the
# partner_type style that _build_context puts in the template ("CUSTOMER").
SOURCE_URL = {
    "customers": "core:customers",
    "vendors": "core:vendors",
    "partners": "core:partners",
    "CUSTOMER": "core:customers",
    "VENDOR": "core:vendors",
    "PARTNER": "core:partners",
}


# Keys must match the container id prefix: "sales" -> #sales-display, etc.


# One template set shared by the create form and the detail view.
TEMPLATE_DETAIL_PARTIAL = "core/settings/partners/partials/partner_detail_partial.html"
TEMPLATE_DETAIL_FULL = "core/settings/partners/partner_detail.html"
TEMPLATE_LIST_PARTIAL = "core/settings/partners/partials/partners_table.html"
TEMPLATE_LIST_FULL = "core/settings/partners/partners_list.html"

# Which partner_type values each list shows. None = no type filter (everyone).
PARTNER_TYPE_FILTER = {
    "CUSTOMER": ["CUSTOMER", "BOTH"],
    "VENDOR": ["VENDOR", "BOTH"],
    "PARTNER": None,
}


def _back_url(request, default="core:partners"):
    return reverse(SOURCE_URL.get(request.GET.get("source"), default))


def _source_for(request, partner=None):
    """?source= wins; otherwise infer it from the partner so reloads and redirects work."""
    source = request.GET.get("source")
    if source in SOURCE_URL:
        return source
    if partner is not None and partner.partner_type == "VENDOR":
        return "VENDOR"
    return "CUSTOMER"


def _detail_template(request):
    return TEMPLATE_DETAIL_PARTIAL if request.headers.get("HX-Request") else TEMPLATE_DETAIL_FULL


def _get_label(partner_type):
    if partner_type == "CUSTOMER":
        label = "Customers"
    elif partner_type == "VENDOR":
        label = "Vendors"
    else:
        label = "Partners"

    return label

@login_required
@require_GET
def get_empty_partner_form(request):
    form = PartnerForm(company=request.company)

    source = _source_for(request)
    context = {"form": form, "back_url": reverse(SOURCE_URL[source]), "back_label": _get_label(source)}
    return _render(request, _detail_template(request), context)


@login_required
@require_GET
def partners_details_view(request, partner_id):
    partner = get_object_or_404(Partner, id=partner_id, company=request.company)

    form = PartnerForm(instance=partner, company=request.company)

    source = _source_for(request, partner)
    context = {
        "partner": partner,
        "form": form,
        "back_url": reverse(SOURCE_URL[source]),
        "back_label": _get_label(source),

    }


    return _render(request, _detail_template(request), context)


@login_required
@require_POST
def edit_partner_view(request, partner_id):
    partner = get_object_or_404(Partner, id=partner_id, company=request.company)

    form = PartnerForm(request.POST, instance=partner, company=request.company)

    if not form.is_valid():
        return htmx_error(
            request,
            form.errors,
            trigger={"PartnerFormValidationError": {"errors": form.errors}},
        )

    try:
        with transaction.atomic():
            form.save()

    except IntegrityError:
        errors = {"__all__": ["A partner with this name or Tax ID already exists."]}
        return htmx_error(
            request,
            errors,
            trigger={"PartnerDuplicateError": {"errors": errors}},
        )

    except ValidationError as e:
        errors = _validation_errors(e)
        return htmx_error(
            request,
            errors,
            trigger={"PartnerValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during partner update")
        return htmx_error(
            request,
            "Failed to update partner. An internal error occurred.",
            trigger={"PartnerServerError": {"message": "Failed to update partner"}},
        )

    return htmx_success(
        request,
        "Partner Updated Successfully.",
    )


@login_required
def get_all_partners(request):
    return get_partners(request, "PARTNER")


@login_required
def get_customers_view(request):
    return get_partners(request, "CUSTOMER")


@login_required
def get_vendors_view(request):
    return get_partners(request, "VENDOR")


def get_partners(request, partner_type):
    # 1. Base query: active partners for the user's company.
    partners = (
        Partner.objects.filter(company=request.company)
        .select_related(
            "payment_term",
            "supplier_payment_term",
            "account_receivable",
            "account_payable",
            "preferred_purchase_currency",
        )
        .order_by("name")
    )

    # 2. Type filter. CUSTOMER / VENDOR also include partners marked BOTH;
    #    PARTNER (the "all" list) applies no type filter.
    allowed_types = PARTNER_TYPE_FILTER.get(partner_type)
    if allowed_types:
        partners = partners.filter(partner_type__in=allowed_types)

    # 3. Search filter (name, email, phone or tax_id)
    search_query = request.GET.get("search_partner", "").strip()
    if search_query:
        partners = partners.filter(
            Q(name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(tax_id__icontains=search_query)
        )

    # 4. Build context
    context = _build_context(request, partners, partner_type)

    # 5. Partial for HTMX, full page otherwise
    template = TEMPLATE_LIST_PARTIAL if request.headers.get("HX-Request") else TEMPLATE_LIST_FULL
    return _render(request, template, context)

def _build_context(request, partners, partner_type):
    paginator = Paginator(partners, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return {
        "summary": {
            "total_count": paginator.count,
        },
        "partners": page_obj,
        "source": partner_type,
        "list_url": reverse(SOURCE_URL[partner_type]),
    }

@login_required
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
            detail_url = reverse("core:partner_detail", kwargs={"partner_id": partner.id})
            # Keep the module in the pushed URL so a reload stays in it.
            detail_url += f"?module={_module(request)}"

    except IntegrityError:
        errors = {"__all__": ["A partner with this name or Tax ID already exists."]}
        return htmx_error(
            request,
            errors,
            trigger={"PartnerDuplicateError": {"errors": errors}},
        )

    except ValidationError as e:
        errors = _validation_errors(e)
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