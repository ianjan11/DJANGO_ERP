# core/services/company_provisioning.py
from django.db import transaction
from accounting.services.localization.loader import install_chart_of_accounts
from accounting.services.localization.parser import L10N_ROOT
from django.db import transaction

from accounting.services.localization.loader import install_chart_of_accounts
from core.models import Company, Country, Currency, Partner
from core.models.currency import CompanyCurrency
from users.models import CompanyMembership


# ==============================================================================
# Service Layer
# ==============================================================================


def resolve_chart_key(country_code: str) -> str:
    """Maps a country code to its corresponding l10n folder.

    Falls back to 'generic' if no country-specific chart exists.
    """
    candidate = country_code.lower()

    if (L10N_ROOT / candidate).exists():
        return candidate
    return "generic"


@transaction.atomic
def provision_company(*, code: str, name: str, country: Country, user, currency: Currency = None) -> Company:
    """Provisions a brand new Company along with its backing Partner identity

    and executes chart of accounts localization.
    """
    if currency is None:
        currency = country.currency

    if currency is None:
        raise ValueError(f"No currency specified and none configured for country {country.code}")

    # 1. Create the backing Partner identity
    partner = Partner.objects.create(
        name=name,
        is_company=True,
        country=country,
    )

    # 2. Create the Company pointing to the Partner
    company = Company.objects.create(
        code=code,
        name=name,
        partner=partner,
        country=country,
        currency=currency,
    )

    # 3. Scope the partner back to the company
    partner.company = company
    partner.save(update_fields=["company"])

    CompanyMembership.objects.create(
        company=company,
        user = user,
        is_active=True,
    )

    CompanyCurrency.objects.create(
        company=company,
        currency=currency,
    )

    # 4. Resolve localization key and load Chart of Accounts/Taxes/Journals
    chart_key = resolve_chart_key(country.code)
    install_chart_of_accounts(company, chart_key)

    return company



