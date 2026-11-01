from decimal import Decimal

from django.core.exceptions import ValidationError

from core.services.currency_exchange_service import _get_rate


def resolve_currency_rate(invoice):

    company_currency = invoice.company.currency

    invoice_currency = invoice.currency

    is_foreign = (
            invoice_currency != company_currency
    )

    foreign_currency = (
        invoice_currency
        if is_foreign
        else None
    )

    if is_foreign:
        rate = _get_rate(
            company=invoice.company,
            currency=invoice_currency,
            date=invoice.issue_date,
        )
        if not rate or rate <= 0:
            raise ValidationError(
                f"No valid exchange rate found for "
                f"{invoice_currency} on {invoice.issue_date}."
            )
    else:
        rate = Decimal("1.000000")

    return rate, is_foreign, foreign_currency, company_currency


