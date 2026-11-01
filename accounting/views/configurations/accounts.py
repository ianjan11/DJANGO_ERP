from django.contrib import messages
from django.contrib.admin.templatetags.admin_list import pagination
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounting.forms.account_form import AccountForm
from accounting.models import Account
from accounting.services.configuration_services.accounts_loader import load_accounts
import logging

from core.utils import htmx_error, htmx_success

logger = logging.getLogger('sales.invoice')


def _build_context(request,accounts):

    paginator = Paginator(accounts, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)


    context = {
        "accounts": page_obj,
    }
    return context


@login_required
def accounts_list_view(request):
    accounts = Account.objects.filter(company=request.company)

    search_account = request.GET.get("search_account")
    allow_reconciliation = request.GET.get("allow_reconciliation")

    if search_account:
        accounts = accounts.filter(
            Q(name__icontains=search_account)
            | Q(description__icontains=search_account)
            | Q(code__icontains=search_account)
            | Q(account_type__name__icontains=search_account)
            | Q(internal_type__icontains=search_account)
        )

    if allow_reconciliation == "true" or allow_reconciliation == "on":
        accounts = accounts.filter(allow_reconciliation=True)

    accounts = accounts.order_by("code")

    context = _build_context(request,accounts)



    template = (
        "accounting/configurations/accounts/partials/accounts_list_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/accounts/accounts_list.html"
    )

    return render(request, template, context)

@login_required
def account_detail(request, account_id):

    account = load_accounts(account_id, request)
    form = AccountForm(
        company=request.company,
        instance=account
    )

    context = {
        "account": account,
        "account_form": form,
    }

    template = (
        'accounting/configurations/accounts/partials/account_detail_partial.html'
        if request.headers.get("HX-Request")
        else 'accounting/configurations/accounts/account_detail.html'
    )

    return render(request, template, context)

@require_POST
def edit_account(request, account_id):
    company = getattr(request, "company", None)
    if not company:
        return htmx_error(
            request,
            "User has no company assigned.",
            trigger={"AccountFailed": {"message": "User has no company assigned."}},
        )

    try:
        with transaction.atomic():
            account = load_accounts(account_id, request, for_update=True)

            form = AccountForm(
                request.POST,
                instance=account,
                company=company,
            )


            if not form.is_valid():
                errors = {
                    field: [str(e) for e in error_list]
                    for field, error_list in form.errors.items()
                }
                return htmx_error(
                    request,
                    errors,
                    trigger={"accountValidationError": {"errors": errors}},
                )

            form.save()

    except ValidationError as e:
        errors = e.message_dict if hasattr(e, "message_dict") else {"__all__": e.messages}
        return htmx_error(
            request,
            errors,
            trigger={"accountValidationError": {"errors": errors}},

        )

    except Exception:
        logger.exception("Unexpected error occurred during account update")
        return htmx_error(
            request,
            "Failed to save account due to an internal server error.",
            trigger={"paymentFailed": {"message": "Failed to save account due to an internal error."}},
        )

    return htmx_success(
        request,
        "Account updated successfully.",
        trigger={"accountSuccess": {"message": "Account updated successfully."}},
        target="#accounting-display",
    )

@login_required
def get_empty_account_form(request):
    form = AccountForm(
        company=request.company,
    )

    context = {
        "account_form": form,
        "account": None,
    }

    template = (
        "accounting/configurations/accounts/partials/accounts_form_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/accounts/accounts_form.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def create_account(request):

    company = request.company

    form = AccountForm(
        data=request.POST,
        company=company,
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
            account = form.save(commit=False)
            account.company = company
            account.save()
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
            "Unexpected error while creating account"
        )

        return htmx_error(
            request,
            "Failed to create account due to an internal server error.",
        )

    accounts = Account.objects.filter(company=request.company)

    context = _build_context(request, accounts)

    template = (
        "accounting/configurations/accounts/partials/accounts_list_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/accounts/accounts_list.html"
    )

    return render(request, template, context)


@login_required
@require_POST
def delete_account(request):
    account_ids = request.POST.getlist("account_ids")



    # 2. Check for empty selection
    if not account_ids:
        return htmx_error(
            request,
            "No accounts were selected for deletion.",
        )

    try:
        with transaction.atomic():
            # 3. Fetch accounts in a single query scoped to user's company
            accounts_qs = Account.objects.filter(
                id__in=account_ids, company=request.company
            ).select_for_update()

            count = accounts_qs.count()
            if count == 0:
                return htmx_error(
                    request, "Selected accounts were not found or access denied."
                )

            # 4. Perform bulk deletion (or model instance loop if custom delete hooks are required)
            # If your Account model relies on custom save/delete methods or signals:
            for account in accounts_qs:
                account.delete()

            # Note: If no custom model .delete() logic is needed, use bulk deletion for maximum speed:
            # accounts_qs.delete()

    except ValidationError as e:
        errors = (
            e.message_dict
            if hasattr(e, "message_dict")
            else {"__all__": e.messages}
        )
        return htmx_error(request, errors)

    except Exception:
        logger.exception("Unexpected error occurred during account deletion")
        return htmx_error(
            request,
            "Failed to delete account(s) due to an internal server error.",
        )

    accounts = Account.objects.filter(company=request.company)

    context = _build_context(request, accounts)

    template = (
        "accounting/configurations/accounts/partials/accounts_list_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/accounts/accounts_list.html"
    )

    return render(request, template, context)

@login_required
@require_POST
def toggle_account_view(request, account_id):
    try:
        with transaction.atomic():
            account = load_accounts(
                account_id,
                request=request,
                for_update=True,
            )

            account.is_active = not account.is_active

            account.save(
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
                "AccountValidationError": {
                    "errors": errors,
                }
            },
        )

    except Exception:
        logger.exception(
            "Unexpected error while toggling account status"
        )

        return htmx_error(
            request,
            "Failed to update account status due to an internal server error.",
        )

    return htmx_success(
        request,
        "account status updated.",
        trigger={
            "AccountUpdated": {
                "message": "Account status updated successfully.",
            }
        },
    )


@login_required
@require_POST
def toggle_account_reconciliation_view(request, account_id):
    try:
        with transaction.atomic():
            account = load_accounts(
                account_id,
                request=request,
                for_update=True,
            )

            account.allow_reconciliation = not account.allow_reconciliation

            account.save(
                update_fields=["allow_reconciliation"],
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
                "AccountValidationError": {
                    "errors": errors,
                }
            },
        )

    except Exception:
        logger.exception(
            "Unexpected error while toggling account reconciliation status"
        )

        return htmx_error(
            request,
            "Failed to update account reconciliation status due to an internal server error.",
        )

    return htmx_success(
        request,
        "account reconciliation status updated.",
        trigger={
            "AccountUpdated": {
                "message": "Account status updated successfully.",
            }
        },
    )