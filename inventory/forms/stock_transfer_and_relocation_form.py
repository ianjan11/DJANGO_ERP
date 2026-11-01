from decimal import Decimal
from django import forms
from inventory.forms.stock_operation_form import selectable_locations
from inventory.models import StockLocation, StockQuant



class StockRelocateForm(forms.Form):
    destination_location = forms.ModelChoiceField(
        queryset=StockLocation.objects.none(),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
        empty_label="Select New Bin / Location",
        required=True,
    )
    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )

    def __init__(self, *args, quant=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            qs = selectable_locations(company).filter(usage=StockLocation.Usage.INTERNAL)
            if quant:
                qs = qs.exclude(pk=quant.location_id)
            self.fields["destination_location"].queryset = qs.order_by("complete_name")

    def clean_reason(self):
        return self.cleaned_data.get("reason") or "Full Bin Relocation"


class PhysicalAdjustmentForm(forms.Form):
    """Form for adjusting on-hand quantities against physical counts."""

    counted_quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-sm text-end fw-bold",
                "step": "any",
            }
        ),
        required=True,
    )
    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "e.g. Q4 Audit Discrepancy, Damaged Goods",
            }
        ),
    )

    expected_quantity = forms.DecimalField(
        max_digits=14,
        decimal_places=6,
        required=True,
        widget=forms.HiddenInput()
    )
