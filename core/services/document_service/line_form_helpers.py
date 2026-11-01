from django.forms import Select
from core.services.currency_exchange_service import CurrencyConversionError, exchange_price, currency_id
from inventory.models import Product
from purchases.models import PurchaseOrder
from datetime import datetime
import logging
from django.utils import timezone
from decimal import Decimal
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce



logger = logging.getLogger(__name__)
PURCHASE_MOVE_TYPES = ("in_invoice", "in_refund")

from django import forms
from django.forms import BaseInlineFormSet


class BaseLineInlineFormSet(BaseInlineFormSet):
    """
    Base FormSet for line items across Account Moves, Sales Orders, and Purchase Orders.
    Ensures `doc` is automatically forwarded to all forms (including `empty_form`).
    """

    def get_form_kwargs(self, index):
        """Forward parent document instance (`self.instance`) as `doc` to every form."""
        kwargs = super().get_form_kwargs(index)
        kwargs['doc'] = self.instance
        return kwargs

    def clean(self):
        """Validate that at least one valid non-deleted line item exists."""
        super().clean()

        if any(self.errors):
            return

        has_valid_item = False

        for form in self.forms:
            if not form.is_valid() or not hasattr(form, 'cleaned_data'):
                continue

            # Skip deleted rows
            if form.cleaned_data.get('DELETE'):
                continue

            # Skip empty/unfilled rows (if custom form method exists)
            if hasattr(form, 'is_empty_row') and form.is_empty_row():
                continue

            product = form.cleaned_data.get('product')
            quantity = form.cleaned_data.get('quantity')

            # Validate valid line entry
            if product and quantity and quantity > 0:
                has_valid_item = True
                break

        if not has_valid_item:
            raise forms.ValidationError("Please add at least one line item with a valid product and quantity.")


def _as_date(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value or timezone.localdate()


class ProductSelect(Select):

    def __init__(self, *args, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.document = document
        self._product_cache = None
        self._convert_ctx = None
        self._convert_ctx_computed = False

    def _get_products(self):
        if self._product_cache is None:
            choice_pks = [
                str(val) for val, _ in self.choices
                if val and str(val).isdigit()
            ]
            if choice_pks:
                products = Product.objects.filter(pk__in=choice_pks).annotate(
                    stock=Coalesce(
                        Sum('stock_moves__quantity'),
                        Value(Decimal('0.00')),
                        output_field=DecimalField(max_digits=12, decimal_places=2)
                    )
                )
            else:
                products = Product.objects.none()

            self._product_cache = {str(p.pk): p for p in products}

        return self._product_cache

    def _get_product(self, pk):
        return self._get_products().get(str(pk))


    def _is_purchase_side(self):
        document = self.document
        if not document:
            return False
        return (
            isinstance(document, PurchaseOrder)
            or getattr(document, "move_type", None) in PURCHASE_MOVE_TYPES
        )

    def _get_convert_ctx(self):
        """(company, currency, date) when conversion is needed, else None. Computed once."""
        if self._convert_ctx_computed:
            return self._convert_ctx
        self._convert_ctx_computed = True

        document = self.document
        company = getattr(document, "company", None)
        currency = getattr(document, "currency", None)
        if company and currency and currency_id(currency) != currency_id(company.currency):
            date = _as_date(getattr(document, "issue_date", None) or getattr(document, "order_date", None))
            self._convert_ctx = (company, currency, date)
        return self._convert_ctx

    def _convert(self, amount):
        """Returns (converted_amount, ok). ok is False when a rate is missing."""
        ctx = self._get_convert_ctx()
        if ctx is None:
            return amount, True
        company, currency, date = ctx
        try:
            return exchange_price(amount, company.currency, currency, company=company, date=date), True
        except CurrencyConversionError:
            logger.warning("No rate %s -> %s on %s", company.currency, currency, date)
            return None, False

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if not value:
            return option

        raw_value = value.value if hasattr(value, "value") else value
        product = self._get_product(raw_value)
        if not product:
            return option

        base_price = (product.product_cost if self._is_purchase_side() else product.default_price) or Decimal("0")
        price, ok = self._convert(base_price)

        attrs = option["attrs"]
        attrs["data-price-company"] = str(base_price)      # company currency, for client-side recalculation
        if ok:
            attrs["data-price"] = str(price)
        else:
            attrs["data-price"] = ""                       # unknown: don't show an unconverted price
            attrs["data-rate-missing"] = "1"

        attrs["data-stock"] = str(product.stock)
        attrs["data-max-discount-percent"] = str(product.max_discount_percent or 0)
        attrs["data-description"] = str(product.description or product.name)
        return option

