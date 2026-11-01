from django import forms
from django.forms.widgets import Select

from accounting.models import AccountMoveLine


class CreditsForm(forms.ModelForm):
    class Meta:
        model = AccountMoveLine
        fields = [
             'product', 'quantity','price_unit',
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'product form-select form-select-sm select2-widget',
            }),

            'quantity': forms.NumberInput(attrs={
                'step': '1',
                'class': 'form-control ',
            }),
            'price_unit': forms.NumberInput(attrs={
                'step': '0.01',
                'class': 'form-control',
            }),

        }
