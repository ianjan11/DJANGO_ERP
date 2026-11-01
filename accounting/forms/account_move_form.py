from django import forms
from django.urls import reverse_lazy
from django.forms import inlineformset_factory

from accounting.models import AccountMoveLine, AccountMove, Account, PaymentTerm, Journal, Tax
from core.models import Currency, Partner
from core.services.document_service.line_form_helpers import ProductSelect, BaseLineInlineFormSet
from inventory.models import Product

LOCKED_STATUSES = (
    AccountMove.State.POSTED,
    AccountMove.State.CANCELLED,
)


class MoveForm(forms.ModelForm):
    """
    Form for editing generic document headers (Invoices, Bills, Journal Entries).
    """

    class Meta:
        model = AccountMove
        fields = [
            'issue_date', 'partner', 'payment_term', 'due_date',
            'currency', 'fulfillment_location', 'ref', 'journal', 'narration'
        ]
        widgets = {
            'issue_date': forms.DateInput(attrs={
                'type': 'date',
                'id': 'date-select',
                'class': 'form-select move-header-field',
            }),
            'partner': forms.Select(attrs={
                'id': 'partner-select',
                'class': 'form-select form-select-sm select2-widget move-header-field',
            }),
            'currency': forms.Select(attrs={
                'id': 'currency-select',
                'class': 'form-select form-select-sm select2-widget',
                'hx-post': reverse_lazy('accounting:invoice_update'),
                'hx-include': '.move-header-field',
                'hx-swap': 'none',
                'hx-confirm': (
                    'Changing currency will recalculate prices using system default prices. '
                    'Manually adjusted prices may be overwritten. Continue?'
                ),
            }),
            'payment_term': forms.Select(attrs={
                'id': 'payment-term-select',
                'class': 'form-select form-select-sm select2-widget move-header-field',
            }),
            'fulfillment_location': forms.Select(attrs={
                'id': 'fulfillment-location-select',
                'class': 'form-select form-select-sm select2-widget move-header-field',
            }),
            'ref': forms.TextInput(attrs={
                'class': 'form-control move-header-field',
            }),
            'journal': forms.Select(attrs={
                'class': 'form-select form-select-sm select2-widget move-header-field',
            }),
            'narration': forms.Textarea(attrs={
                'class': 'form-control move-header-field',
                'rows': 3,
            }),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        if self.company:
            self.fields['currency'].queryset = Currency.objects.filter(
                company_currency__company=self.company,
                company_currency__is_active=True,
            )
            self.fields['partner'].queryset = Partner.objects.filter(company=self.company)
            self.fields['payment_term'].queryset = PaymentTerm.objects.filter(company=self.company)
            self.fields['journal'].queryset = Journal.objects.filter(company=self.company)

        self.fields['payment_term'].required = False

        # Lock header fields if the document is in a locked status
        if self.instance and getattr(self.instance, 'state', None) in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True


class MoveLineForm(forms.ModelForm):
    """
    Form for editing individual move lines.
    Handles both Commercial Product lines and Plain Journal lines.
    """

    class Meta:
        model = AccountMoveLine
        fields = [
            'id', 'line_type', 'product', 'quantity', 'product_uom',
            'price_unit', 'taxes', 'discount_percent', 'description',
            'account', 'debit', 'credit', 'memo', 'partner',
        ]
        widgets = {
            'id': forms.HiddenInput(),
            'line_type': forms.HiddenInput(),

            'product': ProductSelect(attrs={
                'class': 'product form-select form-select-sm select2-widget',
            }),

            'partner': forms.Select(attrs={
                'id': 'partner-select',
                'class': 'form-select form-select-sm select2-widget'
            }),

            'product_uom': forms.Select(attrs={
                'class': 'product form-select form-select-sm select2-widget',
            }),
            'quantity': forms.NumberInput(attrs={
                'step': '1',
                'class': 'form-control',
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
            }),
            'account': forms.Select(attrs={
                'class': 'form-select form-select-sm select2-widget',
            }),
            'debit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'credit': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
            }),
            'memo': forms.TextInput(attrs={
                'class': 'form-control',
            }),
        }

    NON_REQUIRED_FIELDS = (
        'product', 'quantity', 'price_unit', 'account',
        'debit', 'credit', 'taxes', 'partner',
    )

    def __init__(self, *args, doc, **kwargs):
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
        MoveType = AccountMove.MoveType

        account_qs = Account.objects.all()
        tax_qs = Tax.objects.all()

        if doc_type in (MoveType.OUT_INVOICE, MoveType.OUT_REFUND, 'sales_order'):
            account_qs = account_qs.filter(account_type__internal_group='INCOME')
            tax_qs = tax_qs.filter(type_tax_use='SALE')
        elif doc_type in (MoveType.IN_INVOICE, MoveType.IN_REFUND, 'purchase_order'):
            account_qs = account_qs.filter(account_type__internal_group='EXPENSE')
            tax_qs = tax_qs.filter(type_tax_use='PURCHASE')
        elif doc_type == MoveType.PAYMENT:
            account_qs = account_qs.filter(account_type__internal_group__in=['ASSET', 'LIABILITY'])

        # 2. Company boundary
        account_qs = account_qs.filter(company=company)
        tax_qs = tax_qs.filter(company=company)
        partner_qs = Partner.objects.filter(is_active=True, company=company)
        product_qs = Product.objects.filter(company=company)

        # 3. Keep values already saved on this line selectable, even if they
        #    fall outside the scoped querysets (archived, other type, etc.).
        #    Otherwise the widget can't render them and they look "lost".
        instance = self.instance
        if instance.pk:
            if instance.account_id:
                account_qs |= Account.objects.filter(pk=instance.account_id)
            if instance.partner_id:
                partner_qs |= Partner.objects.filter(pk=instance.partner_id)
            if instance.product_id:
                product_qs |= Product.objects.filter(pk=instance.product_id)
            if 'taxes' in self.fields:
                tax_qs |= Tax.objects.filter(pk__in=instance.taxes.values_list('pk', flat=True))

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

        # Lock line fields if parent document or line instance is in a locked status
        doc_state = getattr(doc, 'state', None) or getattr(instance, 'state', None)
        if doc_state in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True

    def is_empty_row(self):
        """Returns True if all editable fields on the row are empty."""
        data = self.data or {}
        prefix = self.prefix

        check_fields = ['product', 'quantity', 'price_unit', 'account', 'debit', 'credit', 'memo']
        return not any(data.get(f'{prefix}-{field}', '').strip() for field in check_fields)

    def clean(self):
        cleaned_data = super().clean()

        if self.is_empty_row():
            return cleaned_data

        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')
        price_unit = cleaned_data.get('price_unit')
        account = cleaned_data.get('account')
        debit = cleaned_data.get('debit')
        credit = cleaned_data.get('credit')

        # FIX: Access move_type via self.doc rather than non-existent self.move
        move_type = getattr(self.doc, 'move_type', None) if self.doc else None

        # --- Commercial Product Line ---
        if product and not account:
            if move_type in (AccountMove.MoveType.OUT_INVOICE, AccountMove.MoveType.OUT_REFUND):
                default_acc = getattr(product, 'revenue_account', None)
            else:
                default_acc = getattr(product, 'expense_account', None)

            # Fall back to product category default stock accounts
            if not default_acc and getattr(product, 'category', None):
                category = product.category
                if move_type in (AccountMove.MoveType.OUT_INVOICE, AccountMove.MoveType.OUT_REFUND):
                    default_acc = category.get_stock_output_account()
                else:
                    default_acc = category.get_stock_input_account()

            if default_acc:
                cleaned_data['account'] = default_acc
            else:
                self.add_error('account', f"Product '{product}' has no default account configured.")

        # --- Plain Journal Line ---
        elif debit or credit or (account and not product):
            if not account:
                self.add_error('account', 'Account is required for journal entries.')
            if debit is None and credit is None:
                self.add_error('debit', 'Specify either debit or credit amount.')

        # --- Incomplete Input ---
        elif (quantity or price_unit) and not product:
            self.add_error('product', 'Please select a product or clear quantity and price.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Dynamically set line_type
        if instance.product_id:
            instance.line_type = AccountMoveLine.LineType.PRODUCT
        else:
            instance.line_type = AccountMoveLine.LineType.PLAIN

        if commit:
            instance.save()
            self.save_m2m()
        return instance


MoveLineFormSet = inlineformset_factory(
    parent_model=AccountMove,
    model=AccountMoveLine,
    form=MoveLineForm,
    formset=BaseLineInlineFormSet,
    fk_name='move',
    extra=0,
    can_delete=True,
)