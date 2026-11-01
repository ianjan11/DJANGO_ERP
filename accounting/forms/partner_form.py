from django import forms
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
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Acme Corporation",
                }
            ),
            "partner_type": forms.Select(
                attrs={"class": "form-control "}
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
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "payment_term": forms.Select(
                attrs={"class": "form-control "}
            ),
            "supplier_payment_term": forms.Select(
                attrs={"class": "form-control "}
            ),
            "preferred_purchase_currency": forms.Select(
                attrs={"class": "form-control select2-widget"}
            ),
            "account_receivable": forms.Select(
                attrs={"class": "form-control select2-widget"}
            ),
            "account_payable": forms.Select(
                attrs={"class": "form-control select2-widget"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
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
            if "account_receivable" in self.fields:
                self.fields["account_receivable"].queryset = (
                    self.fields["account_receivable"]
                    .queryset.filter(company=company)
                )
            if "account_payable" in self.fields:
                self.fields["account_payable"].queryset = (
                    self.fields["account_payable"]
                    .queryset.filter(company=company)
                )