from django import forms
from django.utils import timezone

from core.models import ExchangeRate


class ExchangeRateForm(forms.ModelForm):

    class Meta:
        model = ExchangeRate
        fields = ["rate"]
        widgets = {
            "rate": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "step": "0.000001",
                    "min": "0.000001",
                }
            ),
        }

    def __init__(self, *args, company=None, currency=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.company = company
        self.currency = currency

    def save(self, commit=True):
        instance = super().save(commit=False)

        instance.company = self.company
        instance.currency = self.currency

        if commit:
            instance.save()

        return instance