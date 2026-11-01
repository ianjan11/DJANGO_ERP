from decimal import Decimal, ROUND_HALF_UP
from core.models import Currency, ExchangeRate


class CurrencyConversionError(ValueError):
    pass


def _get_rate(company, currency, date):
    """Latest rate for `currency` (in company base currency) on or before `date`."""
    if currency_id_equals_base(company, currency):
        return Decimal("1")

    row = (
        ExchangeRate.objects
        .filter(company=company, currency=currency, date__lte=date)
        .order_by("-date")
        .first()
    )
    if row is None:
        code = currency.code if hasattr(currency, "code") else _currency_code(currency)
        raise CurrencyConversionError(
            f"No exchange rate for {code} on or before {date}."
        )
    return row.rate


def _currency_code(currency_id_or_pk):
    """Resolve a raw currency PK to its code for error messages."""
    try:
        return Currency.objects.get(pk=currency_id_or_pk).code
    except Currency.DoesNotExist:
        return str(currency_id_or_pk)


def currency_id_equals_base(company, currency):
    return currency_id(company.currency) == currency_id(currency)


def currency_id(currency):
    return currency.pk if hasattr(currency, "pk") else currency


def exchange_price(amount, from_currency, to_currency, company, date, round_result=True):
    """
    Convert `amount` from `from_currency` to `to_currency`, routing through
    `company.base_currency`, using rates effective on or before `date`.
    """
    amount = Decimal(str(amount))

    from_id = currency_id(from_currency)
    to_id = currency_id(to_currency)

    if from_id == to_id:
        result = amount
    else:
        # Step 1: from_currency -> base currency
        from_rate = _get_rate(company, from_currency, date)
        amount_in_base = amount * from_rate

        # Step 2: base currency -> to_currency
        to_rate = _get_rate(company, to_currency, date)
        result = amount_in_base / to_rate

    if round_result:
        to_currency_obj = to_currency if hasattr(to_currency, "decimal_places") else Currency.objects.get(pk=to_id)
        quantum = to_currency_obj.quantum()
        result = result.quantize(quantum, rounding=ROUND_HALF_UP)

    return result