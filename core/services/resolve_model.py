# core/services/source_resolver_service.py
from purchases.models import PurchaseOrder
from sales.models import DeliveryOrder


class UnknownSourceTypeError(Exception):
    pass


def resolve_model(source):
    models = {
        "delivery": DeliveryOrder,
        "purchase": PurchaseOrder,
    }

    if source not in models:
        raise UnknownSourceTypeError(f"Unknown source type '{source}'.")

    return models[source]