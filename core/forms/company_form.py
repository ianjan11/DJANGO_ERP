# core/forms.py
import calendar

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Company, Country, Currency
from core.services.company.company_provisioning import provision_company


class CompanyForm(forms.ModelForm):
    # Delegate to Partner — partner fields managed in form
    vat = forms.CharField(
        label="Tax ID / VAT",
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 12-3456789"}),
    )
    street = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    phone = forms.CharField(
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = Company
        fields = [
            "code",
            "name",
            "country",
            "currency",
            "parent",
            "fiscal_year_start_month",
            "fiscal_year_start_day",
            "lock_date",
            "tax_lock_date",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. JANI"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company name"}),
            "country": forms.Select(attrs={
                'class': 'form-select select2-widget',
            }),
            "currency": forms.Select(attrs={
                'class': 'form-select  select2-widget',
            }),
            "parent": forms.Select(attrs={
                'class': 'form-select  select2-widget',
            }),
            "fiscal_year_start_month": forms.Select(
                choices=[
                    (i, m)
                    for i, m in enumerate(
                        [
                            "January",
                            "February",
                            "March",
                            "April",
                            "May",
                            "June",
                            "July",
                            "August",
                            "September",
                            "October",
                            "November",
                            "December",
                        ],
                        start=1,
                    )
                ],
                attrs={"class": "form-select"},
            ),
            "fiscal_year_start_day": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 31}),
            "lock_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "tax_lock_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "fiscal_year_start_month": "Fiscal Year Start Month",
            "fiscal_year_start_day": "Fiscal Year Start Day",
            "lock_date": "Lock Date (all entries)",
            "tax_lock_date": "Tax Lock Date",
            "parent": "Parent Company",
        }

    def __init__(self, *args, user, **kwargs,):
        super().__init__(*args, **kwargs)
        self.user = user

        self.fields["country"].queryset = Country.objects.all().order_by("name")
        self.fields["currency"].queryset = Currency.objects.all().order_by("name")

        parent_qs = Company.objects.all()
        if self.instance.pk:
            parent_qs = parent_qs.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parent_qs.order_by("code")
        self.fields["parent"].required = False

        if self.instance.pk and hasattr(self.instance, "partner") and self.instance.partner:
            partner = self.instance.partner
            self.fields["vat"].initial = partner.tax_id
            self.fields["street"].initial = partner.address
            self.fields["city"].initial = partner.city
            self.fields["email"].initial = partner.email
            self.fields["phone"].initial = partner.phone

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()

        qs = Company.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise ValidationError(f"A company with code '{code}' already exists.")

        return code

    def clean_fiscal_year_start_day(self):
        day = self.cleaned_data["fiscal_year_start_day"]
        month = self.data.get("fiscal_year_start_month") or self.cleaned_data.get("fiscal_year_start_month")
        if month:
            max_day = calendar.monthrange(2024, int(month))[1]  # leap year, safest upper bound
            if day > max_day:
                raise ValidationError(f"Day {day} is not valid for the selected month.")
        return day

    def clean(self):
        cleaned = super().clean()
        lock_date = cleaned.get("lock_date")
        tax_lock_date = cleaned.get("tax_lock_date")
        if lock_date and tax_lock_date and tax_lock_date < lock_date:
            raise ValidationError("Tax lock date cannot be earlier than the general lock date.")

        parent = cleaned.get("parent")
        if parent and self.instance.pk and self._creates_cycle(parent):
            raise ValidationError("This would create a circular company hierarchy.")

        return cleaned

    def _creates_cycle(self, proposed_parent):
        node = proposed_parent
        while node is not None:
            if node.pk == self.instance.pk:
                return True
            node = node.parent
        return False

    def save(self, commit=True):
        if not commit:
            raise NotImplementedError("CompanyForm requires commit=True.")

        if self.instance.pk:
            return self._save_existing()
        return self._save_new()

    @transaction.atomic
    def _save_new(self):
        # 1. Provision Company + Partner + Run Localization via Service
        company = provision_company(
            code=self.cleaned_data["code"],
            name=self.cleaned_data["name"],
            country=self.cleaned_data["country"],
            user=self.user,
            currency=self.cleaned_data.get("currency"),
        )

        # 2. Update additional metadata on the company
        company.parent = self.cleaned_data.get("parent")
        company.fiscal_year_start_month = self.cleaned_data["fiscal_year_start_month"]
        company.fiscal_year_start_day = self.cleaned_data["fiscal_year_start_day"]
        company.lock_date = self.cleaned_data.get("lock_date")
        company.tax_lock_date = self.cleaned_data.get("tax_lock_date")
        company.is_active = self.cleaned_data.get("is_active", True)
        company.save()

        # 3. Update Partner detail fields
        partner = company.partner
        partner.tax_id = self.cleaned_data.get("vat") or None
        partner.address = self.cleaned_data.get("street", "")
        partner.city = self.cleaned_data.get("city", "")
        partner.email = self.cleaned_data.get("email", "")
        partner.phone = self.cleaned_data.get("phone", "")
        partner.save()

        return company

    def _save_existing(self):
        company = super().save(commit=True)

        # Sync Partner details
        if hasattr(company, "partner") and company.partner:
            partner = company.partner
            partner.name = company.name
            partner.tax_id = self.cleaned_data.get("vat") or None
            partner.address = self.cleaned_data.get("street", "")
            partner.city = self.cleaned_data.get("city", "")
            partner.email = self.cleaned_data.get("email", "")
            partner.phone = self.cleaned_data.get("phone", "")
            partner.save()

        return company