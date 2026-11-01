from django import forms
from django.forms.models import modelformset_factory

from accounting.models import Account
from core.models import Currency


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            'code', 'name', 'account_type', 'currency', 'parent',
            'internal_type', 'is_control_account', 'is_active',
            'allow_reconciliation', 'description',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 1100'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_type': forms.Select(attrs={'class': 'form-select select2-widget '}),
            'currency': forms.Select(attrs={'class': 'form-select select2-widget '}),
            'parent': forms.Select(attrs={'class': 'form-select select2-widget '}),
            'internal_type': forms.Select(attrs={'class': 'form-select'}),
            'is_control_account': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_reconciliation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }


    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.company = company

        parent_qs = Account.objects.all()

        if company:
            parent_qs = parent_qs.filter(company=company)

            self.fields["currency"].queryset = (
                Currency.objects
                .filter(
                    company_currency__company=company,
                    company_currency__is_active=True,
                )
                .distinct()
            )
        else:
            self.fields["currency"].queryset = Currency.objects.none()

        if self.instance.pk:
            parent_qs = parent_qs.exclude(pk=self.instance.pk)

        self.fields["parent"].queryset = parent_qs

    def clean_code(self):
        code = self.cleaned_data['code']
        qs = Account.objects.filter(company=self.company, code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"An account with code '{code}' already exists.")
        return code

    def clean_parent(self):
        # Prevent creating a parent cycle (A -> B -> A) through the tree.
        parent = self.cleaned_data.get('parent')
        node = parent
        while node:
            if self.instance.pk and node.pk == self.instance.pk:
                raise forms.ValidationError("An account cannot be its own ancestor.")
            node = node.parent
        return parent

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.company:
            instance.company = self.company
        if commit:
            instance.save()
        return instance


