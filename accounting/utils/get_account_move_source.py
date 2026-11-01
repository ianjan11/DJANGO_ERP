
from django.urls import reverse

from accounting.models import AccountMove

ORIGIN_TYPE_MODELS = {
    "invoice": AccountMove,
}


ORIGIN_TYPE_URL_NAMES = {
    "invoice": ("accounting:invoice_create_or_detail", "invoice_id"),
}

def get_source(move):
    source = move.origin_type
    if not source:
        return None

    model = ORIGIN_TYPE_MODELS.get(source)
    if not model:
        return None

    obj = model.objects.filter(id=move.origin_id).first()
    if not obj:
        return None

    url_name, kwarg_name = ORIGIN_TYPE_URL_NAMES.get(source, (None, None))
    detail_url = reverse(url_name, kwargs={kwarg_name: obj.id}) if url_name else None

    return {"object": obj, "url": detail_url}