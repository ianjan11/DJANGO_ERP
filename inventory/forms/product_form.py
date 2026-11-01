from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounting.models import Account, Tax
from inventory.models import Product, ProductPrice, ProductsCategory, Uom


# ================================================================
# HELPERS
# ================================================================

def _has_field(model, name):
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def _scope_to_company(form, field_names, model, company):
    """Limit choices to the company's own records (if the model has a company FK)."""
    if not company or not _has_field(model, "company"):
        return
    for name in field_names:
        if name in form.fields:
            form.fields[name].queryset = form.fields[name].queryset.filter(company=company)


def _descendant_ids(category):
    """All ids below `category` in the tree (stops circular parents)."""
    found, frontier = set(), [category.pk]
    while frontier:
        children = list(
            ProductsCategory.objects.filter(parent_id__in=frontier)
            .exclude(pk__in=found)
            .values_list("pk", flat=True)
        )
        found.update(children)
        frontier = children
    return found


# ================================================================
# PRODUCT CATEGORY
# ================================================================

class ProductsCategoryForm(forms.ModelForm):
    """
    form = ProductsCategoryForm(request.POST, company=request.company)
    """

    ACCOUNT_FIELDS = [
        "property_valuation_account",
        "property_stock_input_account",
        "property_stock_output_account",
        "property_cogs_account",
        "property_price_difference_account",
    ]

    class Meta:
        model = ProductsCategory
        fields = ["name", "parent", "is_active"] + [
            "property_valuation_account",
            "property_stock_input_account",
            "property_stock_output_account",
            "property_cogs_account",
            "property_price_difference_account",
        ]

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", 'placeholder': 'Name'}),
            "is_active": forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            "parent": forms.Select(attrs={'class': 'form-select select2-widget '}),
            "property_valuation_account": forms.Select(attrs={'class': 'form-select select2-widget '}),
            "property_stock_input_account": forms.Select(attrs={'class': 'form-select select2-widget '}),
            "property_stock_output_account": forms.Select(attrs={'class': 'form-select select2-widget '}),
            "property_price_difference_account": forms.Select(attrs={'class': 'form-select select2-widget '}),
            "property_cogs_account": forms.Select(attrs={'class': 'form-select select2-widget '}),
        }

        labels = {
            "property_valuation_account": "Inventory valuation account",
            "property_stock_input_account": "Stock input (GRNI) account",
            "property_stock_output_account": "Stock output (GDNI) account",
            "property_cogs_account": "Cost of goods sold account",
            "property_price_difference_account": "Price difference account",
        }
        help_texts = {
            "parent": "Leave empty for a top-level category.",
            "property_valuation_account": "Leave empty to inherit from the parent category.",
            "property_stock_input_account": "Leave empty to inherit from the parent category.",
            "property_stock_output_account": "Leave empty to inherit from the parent category.",
            "property_cogs_account": "Leave empty to inherit from the parent category.",
            "property_price_difference_account": "Leave empty to inherit from the parent category.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            company = self.instance.company
        self.company = company
        if company and not self.instance.company_id:
            self.instance.company = company

        if company:
            self.fields["parent"].queryset = ProductsCategory.objects.filter(company=company)
            for name in self.ACCOUNT_FIELDS:
                self.fields[name].queryset = Account.objects.filter(company=company)

        # A category can't be its own parent or sit under its own children.
        if self.instance.pk:
            blocked = _descendant_ids(self.instance) | {self.instance.pk}
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(pk__in=blocked)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Category name is required.")
        return name

    def clean(self):
        cleaned = super().clean()
        name, parent = cleaned.get("name"), cleaned.get("parent")

        if name:
            qs = ProductsCategory.objects.filter(company=self.company, name__iexact=name, parent=parent)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("name", "A category with this name already exists under the same parent.")

        if parent and self.instance.pk and parent.pk in (_descendant_ids(self.instance) | {self.instance.pk}):
            self.add_error("parent", "A category cannot be placed under itself or one of its children.")
        return cleaned


# ================================================================
# PRODUCT
# ================================================================

class ProductForm(forms.ModelForm):
    """
    form = ProductForm(request.POST, company=request.company)
    """

    class Meta:
        model = Product
        fields = [
            "name", "sku", "barcode", "description",
            "product_type", "category",
            "tracking", "uom", "uom_po",
            "default_price", "product_cost", "profit_margin", "max_discount_percent",
            "revenue_account", "cogs_account", "expense_account",
            "costing_method", "inventory_valuation",
            "purchase_method", "sales_invoicing_method", "return_invoicing_method",
            "sales_taxes", "purchase_taxes",
        ]
        widgets = {
            "name" : forms.TextInput(attrs={"class": "form-control", 'placeholder': 'Name'}),
            "product_type" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "tracking" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "uom" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "uom_po" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "default_price" : forms.NumberInput(attrs={'class': 'form-control number-input'}),
            "product_cost" : forms.NumberInput(attrs={'class': 'form-control number-input'}),
            "profit_margin" : forms.NumberInput(attrs={'class': 'form-control number-input'}),
            "max_discount_percent" : forms.NumberInput(attrs={'class': 'form-control number-input'}),
            "revenue_account" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "cogs_account" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "expense_account" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "costing_method" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "inventory_valuation" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "purchase_method" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "sales_invoicing_method" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "return_invoicing_method" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "sales_taxes": forms.CheckboxSelectMultiple(attrs={
                'class': 'form-control-sm item-taxes',
            }),
            "purchase_taxes":forms.CheckboxSelectMultiple(attrs={
                'class': 'form-control-sm item-taxes',
            }),
            "description": forms.Textarea(attrs={"rows": 1}),
            "category" : forms.Select(attrs={'class': 'form-select select2-widget '}),
            "sku" : forms.TextInput(attrs={'class': 'form-control text-input'}),
            "barcode" : forms.TextInput(attrs={'class': 'form-control text-input'}),

        }


        labels = {
            "uom": "Storage unit of measure",
            "uom_po": "Purchase unit of measure",
            "cogs_account": "COGS account",
            "sales_invoicing_method": "Sales invoicing policy",
            "return_invoicing_method": "Return invoicing policy",
            "purchase_method": "Vendor bill control policy",
        }
        help_texts = {
            "category": "Provides default inventory, stock input/output and COGS accounts.",
            "uom_po": "Defaults to the storage unit if blank. Must be the same dimension.",
            "revenue_account": "Leave empty to use the category's revenue account.",
            "cogs_account": "Leave empty to use the category's COGS account.",
            "expense_account": "Leave empty to use the category's expense account.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            company = self.instance.company
        self.company = company
        if company and not self.instance.company_id:
            self.instance.company = company

        if company:
            self.fields["category"].queryset = ProductsCategory.objects.filter(company=company, is_active=True)
            for name in ("revenue_account", "cogs_account", "expense_account"):
                self.fields[name].queryset = Account.objects.filter(company=company)
            _scope_to_company(self, ["sales_taxes", "purchase_taxes"], Tax, company)
            _scope_to_company(self, ["uom", "uom_po"], Uom, company)
            _scope_to_company(self, ["revenue_account", "cogs_account", "expense_account"], Account, company)
            _scope_to_company(self, ["category"], ProductsCategory, company)

            # 2. Apply specific usage filters independently
            if "sales_taxes" in self.fields:
                self.fields["sales_taxes"].queryset = self.fields["sales_taxes"].queryset.filter(
                    type_tax_use__in=[Tax.TypeTaxUse.SALE, Tax.TypeTaxUse.NONE],
                    is_active=True
                )
            if "purchase_taxes" in self.fields:
                self.fields["purchase_taxes"].queryset = self.fields["purchase_taxes"].queryset.filter(
                    type_tax_use__in=[Tax.TypeTaxUse.PURCHASE, Tax.TypeTaxUse.NONE],
                    is_active=True
                )


        self.fields["uom"].required = False      # enforced in clean() for stockable/consumable
        self.fields["uom_po"].required = False
        self.fields["product_cost"].required = False

    # ---------------- field validation ----------------
    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Product name is required.")
        qs = Product.objects.filter(name__iexact=name)   # model: unique_product_name_ci
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A product with this name already exists.")
        return name

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip()
        if not sku:
            raise forms.ValidationError("SKU is required.")
        qs = Product.objects.filter(sku__iexact=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A product with this SKU already exists.")
        return sku

    def clean_barcode(self):
        barcode = (self.cleaned_data.get("barcode") or "").strip()
        if not barcode:
            return None  # NULL, not "" -- the unique constraint only covers non-null barcodes
        qs = Product.objects.filter(barcode=barcode, company=self.company)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Another product in this company already uses this barcode.")
        return barcode

    def clean_default_price(self):
        v = self.cleaned_data.get("default_price")
        if v is not None and v < 0:
            raise forms.ValidationError("Price cannot be negative.")
        return v

    def clean_product_cost(self):
        v = self.cleaned_data.get("product_cost")
        if v is not None and v < 0:
            raise forms.ValidationError("Cost cannot be negative.")
        return v

    def clean_profit_margin(self):
        v = self.cleaned_data.get("profit_margin")
        if v is not None and v < 0:
            raise forms.ValidationError("Profit margin cannot be negative.")
        return v

    def clean_max_discount_percent(self):
        v = self.cleaned_data.get("max_discount_percent")
        if v is not None and not (Decimal("0") <= v <= Decimal("100")):
            raise forms.ValidationError("Max discount must be between 0 and 100.")
        return v



    # ---------------- cross-field validation (mirrors Product._validate) ----------------
    def clean(self):
        cleaned = super().clean()
        product_type = cleaned.get("product_type")
        tracking = cleaned.get("tracking")
        uom, uom_po = cleaned.get("uom"), cleaned.get("uom_po")
        price, cost = cleaned.get("default_price"), cleaned.get("product_cost")
        is_stockable = product_type in ("storable", "consumable")

        if is_stockable and not uom:
            self.add_error("uom", "A storable or consumable product needs a storage unit of measure.")

        if not is_stockable:
            if tracking and tracking != Product.Tracking.NONE:
                self.add_error("tracking", "Only storable or consumable products can be lot/serial tracked.")
            cleaned["tracking"] = Product.Tracking.NONE
            cleaned["uom_po"] = None
        else:
            if uom and uom_po and uom.category_id != uom_po.category_id:
                self.add_error("uom_po", "The purchase unit must be the same dimension as the storage unit.")
            if tracking == Product.Tracking.SERIAL and uom and uom.rounding != Decimal("1"):
                self.add_error("uom", "A serial-tracked product needs a whole-unit storage unit (rounding = 1).")

        if price is not None and cost is not None and price < cost:
            self.add_error("default_price", "Default price cannot be less than the product cost.")

        # Automated valuation posts to the category's valuation account.
        if cleaned.get("inventory_valuation") == "automated" and product_type == "storable":
            category = cleaned.get("category")
            if category and not category.get_valuation_account():
                self.add_error(
                    "category",
                    "This category (or its parents) has no inventory valuation account, "
                    "which automated valuation requires.",
                )
        return cleaned

# ================================================================
# PRODUCT PRICE
# ================================================================

class ProductPriceForm(forms.ModelForm):
    """
    form = ProductPriceForm(request.POST, product=product)
    """

    class Meta:
        model = ProductPrice
        fields = ["price", "product_cost", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        if product is not None and not self.instance.product_id:
            self.instance.product = product

    def clean(self):
        cleaned = super().clean()
        price, cost = cleaned.get("price"), cleaned.get("product_cost")
        start_date, end_date = cleaned.get("start_date"), cleaned.get("end_date")
        product = self.instance.product if self.instance.product_id else None
        today = timezone.now().date()

        if price is not None and price <= 0:
            self.add_error("price", "Price must be greater than zero.")
        if cost is not None and cost <= 0:
            self.add_error("product_cost", "Cost must be greater than zero.")

        # Only block past dates on create / when changed, so existing prices stay editable.
        if start_date and start_date < today and (not self.instance.pk or "start_date" in self.changed_data):
            self.add_error("start_date", "Start date cannot be in the past.")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be before start date.")

        if price is not None and cost is not None:
            if price < cost:
                self.add_error("price", "Price cannot be less than product cost.")
            elif product and product.profit_margin:   # profit_margin can be None
                minimum = cost * (Decimal("1") + product.profit_margin / Decimal("100"))
                if price < minimum:
                    self.add_error("price", f"Price cannot be less than minimum price ({minimum:.2f}).")

        # Overlap check; a blank end_date means open-ended.
        if product and start_date:
            overlapping = ProductPrice.objects.filter(product=product).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=start_date)
            )
            if end_date:
                overlapping = overlapping.filter(start_date__lte=end_date)
            if self.instance.pk:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            if overlapping.exists():
                self.add_error("start_date", "There is already a price set for this product in the selected date range.")
        return cleaned