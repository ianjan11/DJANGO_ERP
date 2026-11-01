from django.db.models import Q
from django.shortcuts import render

from inventory.forms import StockRelocateForm, PhysicalAdjustmentForm
from inventory.models import StockLocation, StockQuant


def physical_inventory_views(request):
    """View to list stock quants for physical inventory counting and adjustments."""
    # Build query filter for company and locations
    location_id = request.GET.get("location_id")
    search_query = request.GET.get("search", "").strip()


    quants = (
        StockQuant.objects.filter(company=request.company)
        .select_related(
            "product",
            "product__uom",
            "location",
            "package",
            "lot",
        )
        .order_by("location__complete_name", "product__name")
    )

    # Filter by specific location if requested
    if location_id:
        quants = quants.filter(
            Q(location_id=location_id) | Q(location__parent_id=location_id)
        )

    # Search filter (product name/code, location, lot/serial)
    if search_query:
        quants = quants.filter(
            Q(product__name__icontains=search_query)
            | Q(product__sku__icontains=search_query)
            | Q(location__name__icontains=search_query)
            | Q(lot__name__icontains=search_query)
        )

    locations = StockLocation.objects.filter(
        company=request.company,
        usage="internal",
    ).order_by("complete_name")

    relocation_form = StockRelocateForm(company=request.company)

    adjustment_form = PhysicalAdjustmentForm()

    context = {
        "quants": quants,
        "locations": locations,
        "selected_location": location_id,
        "search_query": search_query,
        "relocation_form": relocation_form,
        "adjustment_form": adjustment_form,
    }

    if request.headers.get("HX-Request"):
        return render(
            request,
            "inventory/physical_inventory/partials/physical_inventory_partial.html",
            context,
        )

    return render(
        request,
        "inventory/physical_inventory/physical_inventory.html",
        context,
    )






