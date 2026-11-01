from django.core.exceptions import ValidationError
from inventory.models import StockQuant, StockLocation, Warehouse, Product


def resolve_warehouse(warehouse_id):
    """Fetches a Warehouse instance by ID or raises a ValidationError."""
    if not warehouse_id:
        raise ValidationError("Fulfillment warehouse is required.")

    try:
        return Warehouse.objects.select_related("lot_stock", "view_location").get(id=warehouse_id)
    except (Warehouse.DoesNotExist, ValueError, TypeError):
        raise ValidationError(f"Invalid fulfillment warehouse: '{warehouse_id}'")


def resolve_quant(product, warehouse):
    """
    Returns the primary StockQuant for a storable product within a Warehouse.
    Searches across all sub-locations under the warehouse's main stock location (lot_stock).
    """
    if not product or product.product_type.lower() != "storable":
        return None

    if not warehouse:
        raise ValidationError("Warehouse is required to resolve stock quant.")

    # Target the main stock location of the warehouse (lot_stock)
    root_stock_loc = warehouse.lot_stock or warehouse.view_location

    if not root_stock_loc:
        raise ValidationError(f"Warehouse '{warehouse.name}' has no primary stock location configured.")

    # Fetch quants under this location AND all its child shelves/racks
    quant = (
        StockQuant.objects.filter(
            product=product,
            location__parent_path__startswith=root_stock_loc.parent_path,
        )
        .order_by("-quantity")  # Prioritize quants with available stock
        .first()
    )

    if quant is None:
        raise ValidationError(
            f"No stock quant found for '{product.name}' in warehouse '{warehouse.name}' "
            f"({root_stock_loc.complete_name})."
        )

    return quant


def pre_resolve(payload, warehouse):
    """
    Iterates over payload items, validates products, and resolves
    StockQuant IDs based on the assigned Warehouse.
    """
    # Bulk fetch products to eliminate N+1 queries
    product_ids = [
        row.get("product_id")
        for row in payload.get("items", [])
        if row.get("product_id") and not row.get("delete")
    ]

    products_by_id = Product.objects.in_bulk(product_ids)

    for row in payload.get("items", []):
        if row.get("delete"):
            continue

        product_id = row.get("product_id")
        if not product_id:
            continue

        product = products_by_id.get(int(product_id) if str(product_id).isdigit() else product_id)
        if not product:
            raise ValidationError(f"Invalid product ID: '{product_id}'")

        if product.product_type.lower() == "storable":
            quant = resolve_quant(product, warehouse)
            row["quant_id"] = quant.id
        else:
            row["quant_id"] = None

    return payload