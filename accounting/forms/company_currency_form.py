from django import forms
from django.forms import modelformset_factory

from core.models import Currency
from core.models.currency import CompanyCurrency


class CompanyCurrencyForm(forms.ModelForm):

    class Meta:
        model = CompanyCurrency
        fields = ["currency", "is_active"]

        widgets = {
            "currency": forms.Select(
                attrs={
                    "class": "form-select select2-widget ",
                }
            )
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.company = company

        self.fields["currency"].queryset = Currency.objects.all()

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.company = self.company

        if commit:
            instance.save()

        return instance


CompanyCurrencyFormSet = modelformset_factory(
    CompanyCurrency,
    form=CompanyCurrencyForm,
    extra=0,
    can_delete=True,
)