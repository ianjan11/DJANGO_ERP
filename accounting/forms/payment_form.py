from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from accounting.models import Payment, Journal, PaymentTerm
from core.models import Partner, Currency


LOCKED_STATUSES = (
    "posted", "reconciled", "cancelled"
)


class PaymentForm(forms.ModelForm):
    partner = forms.ModelChoiceField(
        queryset=Partner.objects.all(),
        required=True,
        error_messages={
            "required": "Partner is required.",
            "invalid_choice": "Selected partner is not valid.",
        },
        widget=forms.Select(attrs={'class': 'form-select select2-widget'}),
    )

    class Meta:
        model = Payment
        fields = [
            'date',
            'journal',
            'payment_method',
            'payment_type',
            'partner_type',
            'amount',
            'memo',
            'partner',
            'currency'
        ]

        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'journal': forms.Select(attrs={'class': 'form-select select2-widget'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_type': forms.Select(attrs={'class': 'form-select'}),
            'partner_type': forms.Select(attrs={'class': 'form-select'}),
            'currency': forms.Select(attrs={'class': 'form-select select2-widget'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'memo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. INV/2026/001'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        explicit_company = kwargs.pop('company', None)

        # Robust company resolution fallback order:
        # 1. Explicitly passed company
        # 2. getattr(user, 'company')
        # 3. getattr(user, 'profile').company (if company is stored on user profile)
        self.company = explicit_company or (
            getattr(self.user, 'company', None) or
            getattr(getattr(self.user, 'profile', None), 'company', None)
            if self.user else None
        )

        super().__init__(*args, **kwargs)

        if self.company:
            # 1. Filter Journals (Ensure 'BANK' and 'CASH' choices match uppercase/lowercase in DB)
            self.fields['journal'].queryset = Journal.objects.filter(
                company=self.company,
                type__in=['BANK', 'CASH', 'bank', 'cash']
            )

            # 2. Filter Partners
            self.fields['partner'].queryset = Partner.objects.filter(
                company=self.company,
                is_active=True
            )

            # 3. Filter Currencies safely (Allow active company currencies OR company base currency)
            company_currencies = Currency.objects.filter(
                company_currency__company=self.company,
                company_currency__is_active=True
            )

            # If company currency relation is empty, fallback to active currencies in system
            if not company_currencies.exists():
                company_currencies = Currency.objects.filter(is_active=True)

            self.fields['currency'].queryset = company_currencies

        else:
            # Empty querysets only when absolutely no company context exists anywhere
            self.fields['journal'].queryset = Journal.objects.none()
            self.fields['partner'].queryset = Partner.objects.none()
            self.fields['currency'].queryset = Currency.objects.none()

        # Lock fields if the payment instance is in a locked status
        payment_state = getattr(self.instance, 'state', None) or getattr(self.instance, 'status', None)
        if payment_state in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get('amount')
        partner_type = cleaned_data.get('partner_type')
        partner = cleaned_data.get('partner')

        if amount is None:
            self.add_error('amount', "Payment amount is required.")
        elif amount <= 0:
            self.add_error('amount', "Payment amount must be greater than zero.")

        if partner_type in ['customer', 'vendor'] and not partner:
            self.add_error('partner', 'Partner is required for customer and vendor payments.')

        return cleaned_data