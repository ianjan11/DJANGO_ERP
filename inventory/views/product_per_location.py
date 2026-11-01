from pygments.lexers import data
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from inventory.models import Product,StockLocation,StockQuant

def get_locations_by_warehouse(request,warehouse_id):
    locations = StockLocation.objects.filter(warehouse_id=warehouse_id).values('id','name')
    return JsonResponse({'success': True, 'locations': list(locations)})


def get_product_stock_by_location(request,product_id):
    location_id = request.GET.get('location_id')
    if not location_id:
        return JsonResponse({'error':'location_id is required'},status=400)
    product = get_object_or_404(Product, pk=product_id)
    location = get_object_or_404(StockLocation, pk=location_id)
    quant = (StockQuant.objects.select_related("location", "location__warehouse")
             .filter(location=location,product=product).first())
    return JsonResponse({
        "product": product.name,
        "location": location.name,
        "quant": {
            "id": quant.id if quant else None,
        },
        "warehouse": location.warehouse.name,
        "available": float(quant.quantity - quant.product.reserved_stock) if quant else 0,
        "reserved": float(quant.product.reserved_stock) if quant else 0,
        "on_hand": float(quant.quantity) if quant else 0
    })

