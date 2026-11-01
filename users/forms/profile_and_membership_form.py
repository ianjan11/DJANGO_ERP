from django import forms

from accounting.models import PaymentTerm
from core.models.currency import CompanyCurrency, Currency
from core.utils.form_helpers import _scope_to_company
from inventory.models import StockLocation
from users.models import UserProfile, CompanyMembership
from core.models import Company  # Adjust import path to your Company model if needed


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['default_location', 'default_currency', 'default_payment_term']

        widgets = {
            'default_currency': forms.Select(attrs={'class': 'form-select select2-widget'}),
            'default_location': forms.Select(attrs={'class': 'form-select select2-widget'}),
            'default_payment_term': forms.Select(attrs={'class': 'form-select select2-widget'}),
        }

        labels = {
            'default_payment_term': 'Default Payment Term',
            'default_location': 'Default Location',
            'default_currency': 'Default Currency',
        }

        help_texts = {
            'default_location': "Location to be used as default in document creation",
            'default_payment_term': "Payment term to be used as default in document creation",
            'default_currency': "Currency to be used as default in document creation",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        _scope_to_company(self, ["default_location"], StockLocation, company)
        _scope_to_company(self, ["default_payment_term"], PaymentTerm, company)

        self.fields["default_currency"].queryset = (
                Currency.objects
                .filter(
                    company_currency__company=company,
                    company_currency__is_active=True,
                )
                .distinct()
            )


class CompanyMembershipForm(forms.ModelForm):
    class Meta:
        model = CompanyMembership
        fields = ['company']

        widgets = {
            'company': forms.Select(attrs={'class': 'form-select select2-widget'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        if user:
            # Correct: Query Company instances through the membership relation
            self.fields['company'].queryset = Company.objects.filter(
                memberships__user=user,
                memberships__is_active=True
            )
        else:
            self.fields['company'].queryset = Company.objects.none()