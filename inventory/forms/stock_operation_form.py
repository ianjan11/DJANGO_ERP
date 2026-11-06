from decimal import Decimal
from django.db.models import Q
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from core.models import Partner
from inventory.models import (
    Product,
    StockLocation,
    StockMove,
    StockPicking,
    StockPickingType,
)


LOCKED_STATUSES = (
    StockPicking.Status.COMPLETED,
    StockPicking.Status.CANCELLED,
)


def selectable_locations(company, keep=()):
    """
    Returns stockable locations belonging to the company OR global system locations (Vendors, Customers).
    Excludes VIEW folder nodes. Keeps historical locations if passed in `keep`.
    """
    if not company:
        return StockLocation.objects.none()

    # Allow company-specific OR global shared locations (company=None)
    company_condition = Q(company=company) | Q(company__isnull=True)

    # Must be active AND not a VIEW location
    valid_condition = Q(active=True) & ~Q(usage=StockLocation.Usage.VIEW)

    keep_ids = [pk for pk in keep if pk]
    if keep_ids:
        valid_condition |= Q(pk__in=keep_ids)

    return StockLocation.objects.filter(company_condition).filter(valid_condition)



class StockPickingHeaderForm(forms.ModelForm):
    class Meta:
        model = StockPicking
        fields = [
            "picking_type",
            "partner",
            "source_location",
            "dest_location",
            "scheduled_date",
            "origin",
            "note",
        ]
        widgets = {
            "picking_type": forms.Select(attrs={
                "class": "form-select select2-widget picking-header-field",
                "id": "id_picking_type",
            }),
            "partner": forms.Select(attrs={
                "class": "form-select select2-widget picking-header-field",
                "data-placeholder": "Select Partner / Contact...",
                'id': 'partner-select',

            }),
            "source_location": forms.Select(attrs={
                "class": "form-select select2-widget picking-header-field",
                "id": "id_source_location",
            }),
            "dest_location": forms.Select(attrs={
                "class": "form-select select2-widget picking-header-field",
                "id": "id_dest_location",
            }),
            "scheduled_date": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "class": "form-control picking-header-field",
                    "type": "datetime-local",
                    "id": "date-select",
                },
            ),
            "origin": forms.TextInput(attrs={
                "class": "form-control picking-header-field",
                "placeholder": "e.g. SO001, PO0024...",
            }),

            "note" : forms.TextInput( attrs={
                "class": "form-control picking-header-field",
            } ),
        }
        labels = {
            "picking_type": "Operation Type",
            "partner": "Partner / Contact",
            "source_location": "Source Location",
            "dest_location": "Destination Location",
            "scheduled_date": "Scheduled Date",
            "origin": "Source Document",
            "note": "Note"
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        if company:
            self.fields["picking_type"].queryset = StockPickingType.objects.filter(
                warehouse__company=company,
                active=True,
            )
            self.fields["partner"].queryset = Partner.objects.filter(company=company)
        else:
            self.fields["picking_type"].queryset = StockPickingType.objects.none()
            self.fields["partner"].queryset = Partner.objects.none()

        keep = (self.instance.source_location_id, self.instance.dest_location_id) if self.instance.pk else ()
        locations = selectable_locations(company, keep)
        self.fields["source_location"].queryset = locations
        self.fields["dest_location"].queryset = locations

        # Operation type is fixed once the picking exists (it drives the name/sequence).
        if self.instance.pk:
            self.fields["picking_type"].disabled = True
            if self.instance.status != StockPicking.Status.DRAFT:
                for field in self.fields.values():
                    field.disabled = True

    def clean(self):
        cleaned_data = super().clean()

        source = cleaned_data.get("source_location")
        dest = cleaned_data.get("dest_location")

        if source and dest and source == dest:
            raise ValidationError("Source and destination locations must differ.")

        return cleaned_data


class StockMoveForm(forms.ModelForm):
    class Meta:
        model = StockMove
        fields = ["id","product", "quantity","product_uom", "source_location", "dest_location"]
        widgets = {
            'id': forms.HiddenInput(),

            "product": forms.Select(attrs={
                "class": "form-select select2-widget line-product-select",
                "data-placeholder": "Select Product...",
            }),
            "quantity": forms.NumberInput(attrs={
                "class": "form-control text-end fw-bold",
                "step": "1",
                "min": "1",
                "placeholder": "1",
            }),
            "product_uom": forms.Select(attrs={"class": "form-select select2-widget line-product-select",}),

            "source_location": forms.Select(attrs={"class": "form-select select2-widget line-location"}),
            "dest_location": forms.Select(attrs={"class": "form-select select2-widget line-location"}),
        }
        labels = {"quantity": "Quantity", "source_location": "From", "dest_location": "To", "product_uom": "Uom",}

    def __init__(self, *args, company=None, picking=None, picking_status=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.picking = picking

        for name in ("source_location", "dest_location"):
            self.fields[name].required = False   # blank -> model falls back to header

        if company:
            self.fields["product"].queryset = Product.objects.filter(
                company=company, product_type__in=("storable", "consumable"))
        else:
            self.fields["product"].queryset = Product.objects.none()

        keep = (self.instance.source_location_id, self.instance.dest_location_id) if self.instance.pk else ()
        locations = selectable_locations(company, keep)
        self.fields["source_location"].queryset = locations
        self.fields["dest_location"].queryset = locations

        if picking is not None and not self.instance.pk:
            self.fields["source_location"].initial = picking.source_location_id
            self.fields["dest_location"].initial = picking.dest_location_id

        if picking_status in LOCKED_STATUSES:
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        src, dst = cleaned.get("source_location"), cleaned.get("dest_location")
        if src and dst and src == dst:
            self.add_error("dest_location", "Source and destination locations must differ.")
        return cleaned

StockMoveFormSet = inlineformset_factory(
    parent_model=StockPicking,
    model=StockMove,
    form=StockMoveForm,
    fk_name="picking",
    extra=0,
    can_delete=True,
    fields=[
        "product",
        "quantity",
        "product_uom",
        "source_location",
        "dest_location",
    ],
)





