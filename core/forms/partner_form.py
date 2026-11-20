from django import forms

from accounting.models import Account
from core.models import Partner


class PartnerForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = [
            "name",
            "partner_type",
            "tax_id",
            "email",
            "phone",
            "address",
            "city",
            "payment_term",
            "supplier_payment_term",
            "preferred_purchase_currency",
            "account_receivable",
            "account_payable",
            "is_active",
            "country"
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Acme Corporation",
                }
            ),
            "partner_type": forms.Select(
                attrs={"class": "form-select select2-widget "}
            ),
            "tax_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "TIN Number"}
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "email@example.com",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "+255 700 000 000",
                }
            ),
            "address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Street / Building",
                }
            ),
            "city": forms.TextInput(attrs={"class": "form-control"}),

            "country": forms.Select(attrs={"class": "form-select select2-widget "}),

            "payment_term": forms.Select(
                attrs={"class": "form-control "}
            ),
            "supplier_payment_term": forms.Select(
                attrs={"class": "form-select select2-widget "}
            ),
            "preferred_purchase_currency": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "account_receivable": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "account_payable": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
        }

    def __init__(self, *args, **kwargs):
        """Scope foreign key choices to user's company."""
        company = kwargs.pop("company", None)
        super().__init__(*args, **kwargs)

        if company:
            if "payment_term" in self.fields:
                self.fields["payment_term"].queryset = (
                    self.fields["payment_term"]
                    .queryset.filter(company=company)
                )
            if "supplier_payment_term" in self.fields:
                self.fields["supplier_payment_term"].queryset = (
                    self.fields["supplier_payment_term"]
                    .queryset.filter(company=company)
                )

            accounts = Account.objects.filter(company=company, is_active=True, allow_reconciliation=True)

            self.fields["account_receivable"].queryset = accounts.filter(internal_type="receivable")
            self.fields["account_payable"].queryset = accounts.filter(internal_type="payable")
            for name in ("account_receivable", "account_payable"):
                self.fields[name].required = False
                self.fields[name].empty_label = "Company default"