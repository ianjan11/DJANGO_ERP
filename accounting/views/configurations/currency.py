import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounting.forms.company_currency_form import (
    CompanyCurrencyForm,
    CompanyCurrencyFormSet,
)
from accounting.forms.exchange_rate_form import ExchangeRateForm
from core.models import Currency, ExchangeRate
from core.models.currency import CompanyCurrency
from core.services.exchange_rate_service import ExchangeRateService
from core.utils import htmx_error, htmx_success


logger = logging.getLogger("sales.invoice")


def _build_context(request):
    company = request.company

    company_currencies = (
        CompanyCurrency.objects
        .filter(company=company)
        .select_related("currency")
        .order_by("currency__code")
    )

    search_currency = request.GET.get("search_currency")

    if search_currency:
        company_currencies = company_currencies.filter(
            Q(currency__name__icontains=search_currency)
            | Q(currency__code__icontains=search_currency)
        )

    paginator = Paginator(company_currencies, 10)

    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    today = timezone.localdate()

    for company_currency in page_obj:
        currency = company_currency.currency

        rate = ExchangeRate.objects.filter(
            company=company,
            currency=currency,
            date=today,
        ).first()

        company_currency.rates_form = ExchangeRateForm(
            instance=rate,
            company=company,
            currency=currency,
        )

    formset = CompanyCurrencyFormSet(
        queryset=CompanyCurrency.objects.none(),
        form_kwargs={
            "company": company,
        },
    )

    return {
        "currencies": page_obj,
        "formset": formset,
    }


@login_required
def currency_view(request):
    context = _build_context(request)

    template = (
        "accounting/configurations/currency/currencies_partial.html"
        if request.headers.get("HX-Request")
        else "accounting/configurations/currency/currencies_list.html"
    )

    return render(request, template, context)


@login_required
@require_POST
def save_rate_view(request, currency_id):
    company = request.company

    company_currency = get_object_or_404(
        CompanyCurrency.objects.select_related("currency"),
        company=company,
        currency_id=currency_id,
    )

    currency = company_currency.currency
    today = timezone.localdate()

    rate = ExchangeRate.objects.filter(
        company=company,
        currency=currency,
        date=today,
    ).first()

    rates_form = ExchangeRateForm(
        request.POST,
        instance=rate,
        company=company,
        currency=currency,
    )

    if not rates_form.is_valid():
        return htmx_error(
            request,
            "Please enter a valid currency rate.",
        )

    try:
        with transaction.atomic():
            rate = rates_form.save(commit=False)
            rate.date = today
            rate.company = company
            rate.currency = currency
            rate.save()

    except IntegrityError:
        return htmx_error(
            request,
            "Currency rate already exists.",
        )

    except ValidationError as exc:
        return htmx_error(
            request,
            str(exc),
        )

    except Exception:
        logger.exception(
            "An error occurred while saving currency rate."
        )

        return htmx_error(
            request,
            "Something went wrong.",
        )

    return htmx_success(
        request,
        "Currency rate saved.",
        trigger={
            "RefreshCurrencies": {
                "message": "Currency saved successfully."
            }
        },
    )


@login_required
@require_POST
def sync_rate_view(request):
    try:
        service = ExchangeRateService(
            company=request.company,
        )

        service.run()

    except ValidationError as exc:
        return htmx_error(
            request,
            str(exc),
        )

    except Exception:
        logger.exception(
            "Failed to synchronize exchange rates."
        )

        return htmx_error(
            request,
            "Unable to synchronize exchange rates.",
        )

    return htmx_success(
        request,
        "Synchronized exchange rates.",
        trigger={
            "RefreshCurrencies": {
                "message": "Currency rates synchronized successfully."
            }
        },
    )


@login_required
@require_POST
def toggle_currency_view(request, currency_id):
    company = request.company

    company_currency = get_object_or_404(
        CompanyCurrency,
        company=company,
        currency_id=currency_id,
    )

    # The company's base currency must always remain active.
    if (
        company_currency.currency_id == company.currency_id
        and company_currency.is_active
    ):
        return htmx_error(
            request,
            "The company currency cannot be deactivated.",
        )

    company_currency.is_active = not company_currency.is_active
    company_currency.save(
        update_fields=["is_active"],
    )

    return htmx_success(
        request,
        "Currency status updated.",
        trigger={
            "RefreshCurrencies": {
                "message": "Currency status updated successfully."
            }
        },
    )


@login_required
def get_empty_currency_row(request):
    index = request.GET.get("index", 0)

    form = CompanyCurrencyForm(
        prefix=f"form-{index}",
        company=request.company,
    )

    return render(
        request,
        "accounting/configurations/currency/currency_row_form.html",
        {
            "form": form,
            "form_idx": index,
        },
    )


@login_required
@require_POST
def add_currency_view(request):

    company = request.company

    prefix = request.POST.get("form_prefix")

    if not prefix:
        return htmx_error(
            request,
            "Invalid currency form submission.",
        )

    form = CompanyCurrencyForm(
        data=request.POST,
        prefix=prefix,
        company=company,
    )

    if not form.is_valid():
        errors = {
            field: [str(error) for error in error_list]
            for field, error_list in form.errors.items()
        }

        return htmx_error(
            request,
            errors,
        )

    try:
        with transaction.atomic():
            form.save()

    except IntegrityError:
        return htmx_error(
            request,
            "This currency is already configured for the company.",
        )

    except ValidationError as exc:
        errors = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"__all__": exc.messages}
        )

        return htmx_error(
            request,
            errors,
        )

    except Exception:
        logger.exception(
            "Unexpected error while adding company currency."
        )

        return htmx_error(
            request,
            "Failed to add currency due to an internal server error.",
        )

    return htmx_success(
        request,
        "Currency added successfully.",
        trigger={
            "RefreshCurrencies": {
                "message": "Currency added successfully."
            }
        },
    )


