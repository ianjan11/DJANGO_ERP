# core/services/pricing_service.py
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError

from core.services.currency_exchange_service import exchange_price


def authoritative_price(
    product,
    *,
    price_field="default_price",
    line_uom=None,
    doc_currency=None,
    company=None,
    date=None,
    decimal_places=2,
):
    """
    Single source of truth for 'what should this line's price be'.

    Order of operations (must not change — see ItemsService docstring):
      1. product price in company currency, per its storage UoM
      2. scale to the line's UoM (still company currency)
      3. convert once to the document currency
      4. round once, half-up

    Returns a Decimal quantized to `decimal_places`.
    """
    if product is None:
        return None

    storage = getattr(product, "uom", None)
    uom = line_uom or storage

    price = Decimal(str(getattr(product, price_field, None) or "0"))

    # 2. scale to the line's UoM, in company currency
    if storage is not None and uom is not None and uom.pk != storage.pk:
        if uom.category_id != storage.category_id:
            raise ValidationError(
                f"UoM '{uom}' is incompatible with product UoM '{storage}'."
            )
        factor = uom.convert_to(Decimal("1"), storage)
        if not factor:
            raise ValidationError(
                f"UoM '{uom}' has an invalid conversion factor to '{storage}'."
            )
        price = price * Decimal(str(factor))

    # 3. convert once, on the final amount
    if doc_currency is not None and company is not None:
        target_pk = getattr(doc_currency, "pk", doc_currency)
        if target_pk != getattr(company, "currency_id", None):
            price = exchange_price(
                price,
                company.currency,
                doc_currency,
                company=company,
                date=date,
                round_result=False,
            )

    # 4. round once
    if decimal_places is None:
        return price
    return price.quantize(
        Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP
    )