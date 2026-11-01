from django import forms
from accounting.models import Account, Journal
from core.models.currency import CompanyCurrency, Currency


class JournalForm(forms.ModelForm):
    class Meta:
        model = Journal
        fields = (
            "name",
            "code",
            "type",
            "currency",
            "default_debit_account",
            "default_credit_account",
            "suspense_account",
            "outstanding_receipts_account",
            "outstanding_payments_account",
            "requires_outstanding_reconciliation",
            "notes",
        )

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Customer Invoices",
                }
            ),
            "code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., INV",
                    "maxlength": "10",
                }
            ),
            "type": forms.Select(attrs={"class": "form-select"}),
            "currency": forms.Select(attrs={"class": "form-select select2-widget"}),
            "default_debit_account": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "default_credit_account": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "suspense_account": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "outstanding_receipts_account": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "outstanding_payments_account": forms.Select(
                attrs={"class": "form-select select2-widget"}
            ),
            "requires_outstanding_reconciliation": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional internal notes...",
                }
            ),
        }

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        # Filter related account options to the active company
        company_accounts = Account.objects.filter(company=self.company)
        self.fields["default_debit_account"].queryset = company_accounts
        self.fields["default_credit_account"].queryset = company_accounts
        self.fields["suspense_account"].queryset = company_accounts
        self.fields["outstanding_receipts_account"].queryset = company_accounts
        self.fields["outstanding_payments_account"].queryset = company_accounts

        # Filter active currency options for this company
        self.fields["currency"].queryset = Currency.objects.filter(
            company_currency__company=self.company,
            company_currency__is_active=True,
        )

        self.fields["currency"].empty_label = (
            f"Company Default ({self.company.currency})"
            if hasattr(self.company, "currency")
            else "Use Company Currency"
        )

    def clean_code(self):
        """Ensure code is uppercase and unique per company."""
        code = self.cleaned_data.get("code", "").upper()

        qs = Journal.objects.filter(company=self.company, code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                "A journal with this code already exists for your company."
            )

        return code

    def save(self, commit=True):
        journal = super().save(commit=False)
        journal.company = self.company
        if commit:
            journal.save()
        return journal