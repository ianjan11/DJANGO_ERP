from django import forms
from inventory.models import Warehouse



class WarehouseForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.all(),
        label="Select Warehouse",
        widget=forms.Select(
            attrs={
                'class': 'form-select',
            }
        )
    )
