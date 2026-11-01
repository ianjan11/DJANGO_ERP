from decimal import Decimal

from django import forms
from django.db.models import Q

from accounting.models import Account
from accounting.models.tax import Tax, TaxGroup


class TaxForm(forms.ModelForm):

    class Meta:
        model = Tax
        fields = [
            "name",
            "type_tax_use",
            "computation",
            "rate",
            "sequence",
            "parent_tax",
            "account",
            "account_refund",
            "tax_group",
            "price_include",
            "include_base_amount",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. VAT 18%",
                }
            ),

            "type_tax_use": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "computation": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "rate": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.00001",
                    "min": "0",
                    "placeholder": "e.g. 18",
                }
            ),

            "sequence": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                }
            ),

            "parent_tax": forms.Select(
                attrs={
                    "class": "form-select select2-widget",
                }
            ),

            "account": forms.Select(
                attrs={
                    "class": "form-select select2-widget",
                }
            ),

            "account_refund": forms.Select(
                attrs={
                    "class": "form-select select2-widget",
                }
            ),

            "tax_group": forms.Select(
                attrs={
                    "class": "form-select select2-widget",
                }
            ),

            "price_include": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),

            "include_base_amount": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),

            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.company = company

        # ---------------------------------------------------------
        # Accounts
        # ---------------------------------------------------------
        account_qs = Account.objects.none()

        if company:
            account_qs = Account.objects.filter(
                company=company,
                is_active=True,
            ).order_by("code")

        self.fields["account"].queryset = account_qs
        self.fields["account_refund"].queryset = account_qs

        # ---------------------------------------------------------
        # Parent taxes
        # ---------------------------------------------------------
        parent_qs = Tax.objects.none()

        if company:
            parent_qs = Tax.objects.filter(
                company=company,
                is_active=True,
            )

            # Existing parent remains selectable even if inactive.
            if self.instance.pk and self.instance.parent_tax_id:
                parent_qs = Tax.objects.filter(
                    Q(
                        company=company,
                        is_active=True,
                    )
                    | Q(
                        pk=self.instance.parent_tax_id,
                    )
                )

        # A tax cannot be its own parent.
        if self.instance.pk:
            parent_qs = parent_qs.exclude(pk=self.instance.pk)

        self.fields["parent_tax"].queryset = parent_qs.order_by(
            "sequence",
            "name",
            "id",
        )

        # ---------------------------------------------------------
        # Tax groups
        # ---------------------------------------------------------
        self.fields["tax_group"].queryset = TaxGroup.objects.all()

    # =============================================================
    # FIELD VALIDATION
    # =============================================================

    def clean_rate(self):
        rate = self.cleaned_data.get("rate")
        computation = self.cleaned_data.get("computation")

        if rate is None:
            return rate

        if rate < Decimal("0"):
            raise forms.ValidationError(
                "Tax rate cannot be negative."
            )

        if computation == "PERCENT" and rate > Decimal("100"):
            raise forms.ValidationError(
                "Percentage tax rate cannot exceed 100%."
            )

        return rate

    def clean_parent_tax(self):
        parent_tax = self.cleaned_data.get("parent_tax")

        if not parent_tax:
            return parent_tax

        if self.instance.pk and parent_tax.pk == self.instance.pk:
            raise forms.ValidationError(
                "A tax cannot be its own parent."
            )

        if self.company and parent_tax.company_id != self.company.pk:
            raise forms.ValidationError(
                "Parent tax must belong to the current company."
            )

        return parent_tax

    # =============================================================
    # CROSS-FIELD VALIDATION
    # =============================================================

    def clean(self):
        cleaned_data = super().clean()

        computation = cleaned_data.get("computation")
        parent_tax = cleaned_data.get("parent_tax")
        type_tax_use = cleaned_data.get("type_tax_use")
        account = cleaned_data.get("account")
        account_refund = cleaned_data.get("account_refund")

        # ---------------------------------------------------------
        # GROUP TAX
        # ---------------------------------------------------------
        if computation == "GROUP":
            if not parent_tax:
                self.add_error(
                    "parent_tax",
                    "A group tax must have a parent tax."
                )

        # ---------------------------------------------------------
        # NORMAL TAX
        # ---------------------------------------------------------
        elif parent_tax:
            self.add_error(
                "parent_tax",
                "Parent tax is only used for group taxes."
            )

        # ---------------------------------------------------------
        # Parent tax must have compatible tax usage
        # ---------------------------------------------------------
        if parent_tax and type_tax_use:
            if (
                parent_tax.type_tax_use != type_tax_use
                and parent_tax.type_tax_use != "NONE"
            ):
                self.add_error(
                    "parent_tax",
                    "Parent tax must have the same tax usage."
                )

        # ---------------------------------------------------------
        # Account company validation
        # ---------------------------------------------------------
        if account and self.company:
            if account.company_id != self.company.pk:
                self.add_error(
                    "account",
                    "Tax account must belong to the current company."
                )

        if account_refund and self.company:
            if account_refund.company_id != self.company.pk:
                self.add_error(
                    "account_refund",
                    "Refund account must belong to the current company."
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        if self.company:
            instance.company = self.company

        if commit:
            instance.save()

        return instance