from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounting.forms.journal_form import JournalForm
from accounting.models import Account, Journal
from accounting.services.account_move_services.journal_loader import load_Journal
import logging

from core.utils import htmx_error, htmx_success

logger = logging.getLogger('django.request')

def _build_context(request,journals):

    paginator = Paginator(journals, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "journals": page_obj,
    }
    return context

@login_required
def journals_list_view(request):
    journals = Journal.objects.filter(company=request.company)

    search_journal = request.GET.get("search_journal")

    if search_journal:
        journals = journals.filter(
            Q(name__icontains=search_journal)
            | Q(code__icontains=search_journal)
            | Q(type__icontains=search_journal)
        )

    journals = journals.order_by("code")

    context = _build_context(request,journals)



    template = (
        "accounting/configurations/journals/partials/journals_list_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/journals/journals_list.html"
    )

    return render(request, template, context)

@login_required
def journal_detail(request, journal_id):

    journal = load_Journal(journal_id, request)

    form = JournalForm(
        company=request.company,
        instance=journal
    )

    context = {
        "journal": journal,
        "form": form,
    }

    template = (
        'accounting/configurations/journals/partials/journal_detail_partial.html'
        if request.headers.get("HX-Request")
        else 'accounting/configurations/journals/journal_detail.html'
    )

    return render(request, template, context)

@login_required
@require_POST
def edit_journal(request, journal_id):
    company = request.company
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"JournalFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            journal = load_Journal(journal_id, request, for_update=True)

            form = JournalForm(company, request.POST, instance=journal)

            if not form.is_valid():
                errors = {
                    field: [str(e) for e in error_list]
                    for field, error_list in form.errors.items()
                }
                return htmx_error(
                    request,
                    errors,
                    trigger={"journalValidationError": {"errors": errors}},
                )

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"journalValidationError": {"errors": errors}},
        )

    except Exception:
        logger.exception("Unexpected error occurred during journal update")
        return htmx_error(
            request,
            "Failed to save journal due to an internal server error.",
            trigger={"journalFailed": {"message": "Failed to save journal due to an internal error."}},
        )

    return htmx_success(
        request,
        "Journal updated successfully.",
        trigger={"JournalSuccess": {"message": "Journal updated successfully."}},
        target="#accounting-display",
    )

@login_required
def get_empty_journal_form(request):
    form = JournalForm(company=request.company)

    context = {
        "form": form,
        "journal": None,
    }

    template = (
        "accounting/configurations/journals/partials/journal_form_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/journals/journal_form.html"
    )

    return render(request, template, context)


@login_required
@require_POST
def create_journal(request):

    company = request.company

    form = JournalForm(
        company,
        data=request.POST,
    )

    if not form.is_valid():
        errors = {
            field: [str(e) for e in error_list]
            for field, error_list in form.errors.items()
        }

        return htmx_error(
            request,
            errors,
        )

    try:
        with transaction.atomic():
            journal = form.save(commit=False)
            journal.company = company
            journal.save()
            form.save_m2m()

            redirect_url = reverse("accounting:company_journal_detail", args=[journal.id])


    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )

        return htmx_error(request, errors)

    except Exception:
        logger.exception(
            "Unexpected error while creating journal"
        )

        return htmx_error(
            request,
            "Failed to create journal due to an internal server error.",
        )

    return htmx_success(
        request,
        "Journal created successfully.",
        redirect_url=redirect_url,
    )


@login_required
@require_POST
def delete_journal(request):
    journal_ids = request.POST.getlist("journal_ids")


    # 2. Check for empty selection
    if not journal_ids:
        return htmx_error(
            request,
            "No journals were selected for deletion.",
        )

    try:
        with transaction.atomic():
            # 3. Fetch journals in a single query scoped to user's company
            journals_qs = Journal.objects.filter(
                id__in=journal_ids, company=request.company
            ).select_for_update()

            count = journals_qs.count()
            if count == 0:
                return htmx_error(
                    request, "Selected journals were not found or access denied."
                )

            # 4. Perform bulk deletion (or instance loop if hooks are required)
            for journal in journals_qs:
                journal.delete()

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error occurred during journal deletion")
        return htmx_error(
            request,
            "Failed to delete journal(s) due to an internal server error.",
        )

    journals = Journal.objects.filter(company=request.company)

    context = _build_context(request, journals)

    return htmx_success(
        request,
        "Journal deleted successfully.",
        trigger={"JournalSuccess": {"message": "Journal deleted successfully."}},
    )