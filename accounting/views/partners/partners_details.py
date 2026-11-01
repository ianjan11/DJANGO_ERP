from django.db import transaction, IntegrityError
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from prompt_toolkit.validation import ValidationError

from accounting.forms.partner_form import PartnerForm
from core.models import Partner
from core.utils import htmx_error, htmx_success
import logging

logger = logging.getLogger('sales.invoice')


def partners_details_view(request, partner_id):
    partner = Partner.objects.filter(id=partner_id, company=request.company).first()

    form = PartnerForm(request.POST or None, instance=partner)

    context = {
        'partner': partner,
        'form': form,
    }

    if request.headers.get("HX-Request"):
        return render(request, "accounting/partners/partials/partner_detail_partial.html", context)

    return render(request, "accounting/partners/partner_detail.html", context)

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
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
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