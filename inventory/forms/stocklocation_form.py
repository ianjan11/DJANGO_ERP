from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from inventory.models import StockLocation


class StockLocationForm(forms.ModelForm):
    class Meta:
        model = StockLocation
        fields = [
            'name',
            'usage',
            'parent',
            'barcode',
            'posx',
            'posy',
            'posz',
            'scrap_location',
            'return_location',
            'replenish_location',
            'removal_strategy',
            'note',
            'active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Shelf 1',
                'autofocus': True,
            }),
            'usage': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. LOC-001'}),
            'posx': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'posy': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'posz': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'removal_strategy': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'scrap_location': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'return_location': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'replenish_location': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        # Order parents by hierarchy path
        parent_qs = StockLocation.objects.order_by('complete_name')

        # Filter choices: show locations for current company + shared virtual locations
        if company:
            parent_qs = parent_qs.filter(Q(company=company) | Q(company__isnull=True))

        # Prevent circular tree structures when editing an existing location
        if self.instance and self.instance.pk:
            descendant_ids = list(self.instance.descendants(include_self=True).values_list('id', flat=True))
            parent_qs = parent_qs.exclude(id__in=descendant_ids)

        self.fields['parent'].queryset = parent_qs

    def clean_barcode(self):
        barcode = self.cleaned_data.get('barcode', '')
        if isinstance(barcode, str):
            barcode = barcode.strip()
        return barcode if barcode else None

    def clean(self):
        cleaned_data = super().clean()
        parent = cleaned_data.get('parent')
        barcode = cleaned_data.get('barcode')
        company = self.company  # Fixed: use self.company passed to __init__

        # Company mismatch check
        if parent and parent.company_id and company and parent.company_id != company.id:
            self.add_error('parent', f'Parent location belongs to another company ({parent.company.name}).')

        # Barcode uniqueness check per company
        if barcode:
            qs = StockLocation.objects.filter(barcode=barcode)
            if company:
                qs = qs.filter(company=company)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error('barcode', 'This barcode is already assigned to another location in this company.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.company and not instance.company_id:
            instance.company = self.company
        if commit:
            instance.save()
        return instance