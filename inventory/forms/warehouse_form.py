from django import forms

from inventory.models import Warehouse


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            'name',
            'code',
            'sequence',
            'reception_steps',
            'delivery_steps',
            'active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Central Warehouse',
                'autofocus': True,
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. WH1',
            }),
            'sequence': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'reception_steps': forms.Select(attrs={'class': 'form-select'}),
            'delivery_steps': forms.Select(attrs={'class': 'form-select'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, company=None, **kwargs):
        """
        Accepts 'company' directly from request.company in views.
        """
        self.company = company
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data.get('code', '').upper().strip()

        # Target company derived from passed argument or existing instance
        target_company = self.company or (self.instance.company if self.instance.pk else None)

        if code and target_company:
            qs = Warehouse.objects.filter(code=code, company=target_company)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A warehouse with this code already exists for this company.")

        return code

    def save(self, commit=True):
        instance = super().save(commit=False)

        # 1. Ensure company is attached
        target_company = self.company or getattr(instance, 'company', None)
        if target_company and not instance.company_id:
            instance.company = target_company

        # 2. Derive partner directly from company.partner
        if target_company and hasattr(target_company, 'partner'):
            instance.partner = target_company.partner

        if commit:
            instance.save()
            self.save_m2m()

        return instance