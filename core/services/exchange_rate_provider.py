# accounting/services/exchange_rate_provider.py

import requests
from django.conf import settings


class ExchangeRateAPIError(Exception):
    pass


class ExchangeRateProvider:

    BASE_URL = "https://v6.exchangerate-api.com/v6"

    def fetch_rates(self, base_currency):
        api_key = settings.EXCHANGE_RATE_API_KEY

        if not api_key:
            raise ExchangeRateAPIError(
                "Exchange rate API key is not configured."
            )

        url = f"{self.BASE_URL}/latest/{base_currency}"

        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                },
                timeout=10,
            )

            response.raise_for_status()

        except requests.RequestException as exc:
            raise ExchangeRateAPIError(
                "Unable to connect to exchange rate provider."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ExchangeRateAPIError(
                "Exchange rate provider returned invalid data."
            ) from exc

        if data.get("result") != "success":
            raise ExchangeRateAPIError(
                data.get(
                    "error-type",
                    "Exchange rate API error."
                )
            )

        return data


