from django import forms
from django.forms import inlineformset_factory
from django.urls import reverse_lazy

from accounting.models import PaymentTerm, Tax, AccountMove, Account
from core.models import Currency, Partner
from core.services.document_service.line_form_helpers import ProductSelect, BaseLineInlineFormSet
from inventory.models import Product
from sales.models import SalesOrder, SalesOrderLine


LOCKED_STATUSES = (
    "DONE",
    "CANCELLED",
    "SENT",
    "CONFIRMED",
)


class SalesOrderForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ['issue_date', 'partner', 'fulfillment_location', 'currency', 'payment_term']
        widgets = {
            'issue_date': forms.DateInput(attrs={
                'type': 'date',
                'id': 'date-select',
                'class': 'form-select order-header-field ',
            }),
            'partner': forms.Select(attrs={
                'id': 'partner-select',
                'class': 'form-select form-select-sm select2-widget order-header-field',
            }),
            'fulfillment_location': forms.Select(attrs={
                'id': 'location-select',
                'class': 'form-select form-select-sm select2-widget order-header-field',
            }),
            'currency': forms.Select(attrs={
                'id': 'currency-select',
                'class': 'form-select form-select-sm select2-widget',
                'hx-post': reverse_lazy('sales:sales_order_update'),
                'hx-include': '.order-header-field',
                'hx-swap': 'none',
                'hx-confirm': (
                    'Changing currency will recalculate prices using system default prices. '
                    'Manually adjusted prices may be overwritten. Continue?'
                ),
            }),
            'payment_term': forms.Select(attrs={
                'id': 'payment-term-select',
                'class': 'form-select form-select-sm select2-widget order-header-field',
            }),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        if self.company:
            self.fields["currency"].queryset = Currency.objects.filter(
                company_currency__company=self.company,
                company_currency__is_active=True,
            )

            self.fields["partner"].queryset = Partner.objects.filter(
                company=self.company,
            )

            self.fields["payment_term"].queryset = PaymentTerm.objects.filter(
                company=self.company,
            )

        # Lock form fields if the sales order instance is in a locked status
        doc_status = getattr(self.instance, 'status', None) or getattr(self.instance, 'state', None)
        if doc_status in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True


class SalesOrderLineForm(forms.ModelForm):
    class Meta:
        model = SalesOrderLine
        fields = [
            'id', 'product', 'quantity', 'price_unit',
            'taxes', 'discount_percent', 'description', 'product_uom'
        ]
        widgets = {
            'id': forms.HiddenInput(),
            'product': ProductSelect(attrs={
                'class': 'product form-select form-select-sm select2-widget',
            }),
            'product_uom': forms.Select(attrs={
                'class': 'product form-select form-select-sm select2-widget',
            }),
            'quantity': forms.NumberInput(attrs={
                'step': '1',
                'class': 'form-control ',
            }),
            'price_unit': forms.NumberInput(attrs={
                'step': '0.01',
                'class': 'form-control',
            }),
            'taxes': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-control-sm item-taxes',
            }),
            'discount_percent': forms.NumberInput(attrs={
                'step': '0.01',
                'class': 'form-control',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 1,
                'placeholder': 'description',
            })
        }

    NON_REQUIRED_FIELDS = (
        'product', 'quantity', 'price_unit', 'account',
        'debit', 'credit', 'taxes', 'partner', 'description',
    )

    def __init__(self, *args, doc, **kwargs):
        """
        :param doc: The parent document instance. MUST NOT BE NONE.
        """
        if doc is None:
            raise ValueError(
                f"{self.__class__.__name__} instantiation failed: `doc` cannot be None. "
                f"A parent document is required to scope form choices by company."
            )

        super().__init__(*args, **kwargs)
        self.doc = doc

        company = getattr(doc, 'company', None)
        if company is None:
            raise ValueError(
                f"{self.__class__.__name__} initialization error: "
                f"parent document {doc} has no `company` assigned."
            )

        if 'product' in self.fields:
            self.fields['product'].widget.document = doc

        # Polymorphic fields are validated together in clean(), not individually.
        for name in self.NON_REQUIRED_FIELDS:
            if name in self.fields:
                self.fields[name].required = False

        # 1. Scope accounts and taxes by document type
        doc_type = getattr(doc, 'move_type', None) or getattr(doc, 'doc_type', None)
        MoveType = getattr(AccountMove, 'MoveType', None)

        account_qs = Account.objects.all()
        tax_qs = Tax.objects.all()

        if MoveType and doc_type in (MoveType.OUT_INVOICE, MoveType.OUT_REFUND, 'sales_order'):
            account_qs = account_qs.filter(account_type__internal_group='INCOME')
            tax_qs = tax_qs.filter(type_tax_use='SALE')
        elif MoveType and doc_type in (MoveType.IN_INVOICE, MoveType.IN_REFUND, 'purchase_order'):
            account_qs = account_qs.filter(account_type__internal_group='EXPENSE')
            tax_qs = tax_qs.filter(type_tax_use='PURCHASE')
        elif doc_type == 'sales_order':
            tax_qs = tax_qs.filter(type_tax_use='SALE')
        elif doc_type == 'purchase_order':
            tax_qs = tax_qs.filter(type_tax_use='PURCHASE')
        elif MoveType and doc_type == MoveType.PAYMENT:
            account_qs = account_qs.filter(account_type__internal_group__in=['ASSET', 'LIABILITY'])

        # 2. Company boundary
        account_qs = account_qs.filter(company=company)
        tax_qs = tax_qs.filter(company=company)
        partner_qs = Partner.objects.filter(is_active=True, company=company)
        product_qs = Product.objects.filter(company=company)

        # 3. Keep values already saved on this line OR submitted in POST selectable,
        #    even if they fall outside the scoped querysets (archived, other type, etc.).
        #    Otherwise Django form validation drops them during clean().
        instance = self.instance

        def _get_posted_ids(field_name):
            if self.is_bound and self.prefix:
                key = f"{self.prefix}-{field_name}"
                raw = self.data.getlist(key) or self.data.get(key)
                if raw:
                    return [r for r in (raw if isinstance(raw, list) else [raw]) if r]
            return []

        # Preserve Accounts
        account_ids = _get_posted_ids('account')
        if instance and instance.pk and getattr(instance, 'account_id', None):
            account_ids.append(instance.account_id)
        if account_ids:
            account_qs |= Account.objects.filter(pk__in=account_ids)

        # Preserve Taxes
        tax_ids = _get_posted_ids('taxes')
        if instance and instance.pk and hasattr(instance, 'taxes'):
            tax_ids.extend(instance.taxes.values_list('pk', flat=True))
        if tax_ids:
            tax_qs |= Tax.objects.filter(pk__in=tax_ids)

        # Preserve Partners
        partner_ids = _get_posted_ids('partner')
        if instance and instance.pk and getattr(instance, 'partner_id', None):
            partner_ids.append(instance.partner_id)
        if partner_ids:
            partner_qs |= Partner.objects.filter(pk__in=partner_ids)

        # Preserve Products
        product_ids = _get_posted_ids('product')
        if instance and instance.pk and getattr(instance, 'product_id', None):
            product_ids.append(instance.product_id)
        if product_ids:
            product_qs |= Product.objects.filter(pk__in=product_ids)

        # 4. Apply
        scoped = {
            'account': account_qs,
            'taxes': tax_qs,
            'partner': partner_qs,
            'product': product_qs,
        }
        for name, qs in scoped.items():
            if name in self.fields:
                self.fields[name].queryset = qs.distinct()

        # Disable fields when the parent document or line instance status is locked
        doc_status = getattr(doc, 'status', None) or getattr(doc, 'state', None) or getattr(instance, 'status', None) or getattr(instance, 'state', None)
        if doc_status in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True

    def is_empty_row(self):
        data = self.data or {}
        prefix = self.prefix
        product = data.get(f"{prefix}-product", "").strip()
        quantity = data.get(f"{prefix}-quantity", "").strip()
        price = data.get(f"{prefix}-price_unit", "").strip()
        return not product and not quantity and not price

    def clean(self):
        cleaned_data = super().clean()

        # Completely empty row — skip validation, let formset ignore it
        if self.is_empty_row():
            return cleaned_data

        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')
        price_unit = cleaned_data.get('price_unit')

        quantity_filled = quantity is not None and quantity != ''
        price_filled = price_unit is not None and price_unit != ''

        # Product selected but missing required fields
        if product:
            if not quantity_filled:
                self.add_error('quantity', 'Required when a product is selected.')
            if not price_filled:
                self.add_error('price_unit', 'Required when a product is selected.')

        # Fields filled but no product selected
        if not product and (quantity_filled or price_filled):
            self.add_error('product', 'Please select a product.')

        return cleaned_data

    def clean_description(self):
        description = self.cleaned_data.get('description')
        return description.strip() if description else ''


SalesOrderLineFormSet = inlineformset_factory(
    parent_model=SalesOrder,
    model=SalesOrderLine,
    form=SalesOrderLineForm,
    formset=BaseLineInlineFormSet,
    extra=0,
    can_delete=True,
)