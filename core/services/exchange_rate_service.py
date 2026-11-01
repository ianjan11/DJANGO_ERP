# core/services/exchange_rate_service.py

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Currency, ExchangeRate
from core.services.exchange_rate_provider import ExchangeRateProvider


class ExchangeRateService:

    def __init__(self, company):
        self.company = company
        self.company_currency = company.currency
        self.provider = ExchangeRateProvider()

    def fetch_rates(self):
        """
        Fetch rates using the company's currency as the API base currency.
        """
        return self.provider.fetch_rates(
            self.company_currency.code
        )

    def prepare_rates(self, data):
        """
        Convert provider rates into the ERP convention:

            1 foreign currency = X company currency

        ExchangeRate-API gives:

            1 company currency = X foreign currency

        Therefore foreign currency rates are inverted.
        """

        conversion_rates = data.get("conversion_rates")

        if not conversion_rates:
            raise ValidationError(
                "Exchange rate provider returned no conversion rates."
            )

        currencies = Currency.objects.filter(
            is_active=True
        )

        rates = {}

        for currency in currencies:

            # Company currency is always exactly 1.
            if currency.pk == self.company_currency.pk:
                rates[currency] = Decimal("1")
                continue

            api_rate = conversion_rates.get(currency.code)

            if api_rate is None:
                raise ValidationError(
                    f"Exchange rate for {currency.code} "
                    f"is not available from the provider."
                )

            try:
                api_rate = Decimal(str(api_rate))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Invalid exchange rate received for "
                    f"{currency.code}."
                ) from exc

            if api_rate <= 0:
                raise ValidationError(
                    f"Invalid exchange rate received for "
                    f"{currency.code}."
                )

            # API:
            #   1 company currency = X foreign currency
            #
            # ERP:
            #   1 foreign currency = X company currency
            erp_rate = Decimal("1") / api_rate

            rates[currency] = erp_rate

        return rates

    @transaction.atomic
    def update_rates(self, rates):
        """
        Create or update today's exchange rates for this company.
        """

        today = timezone.localdate()

        updated = []

        for currency, rate in rates.items():

            exchange_rate, created = ExchangeRate.objects.update_or_create(
                company=self.company,
                currency=currency,
                date=today,
                defaults={
                    "rate": rate,
                },
            )

            updated.append(exchange_rate)

        return updated

    @transaction.atomic
    def run(self):
        """
        Fetch, prepare and save the company's exchange rates.
        """

        data = self.fetch_rates()

        rates = self.prepare_rates(data)

        exchange_rates = self.update_rates(rates)

        return exchange_rates