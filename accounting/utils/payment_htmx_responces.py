import json
from django.http import HttpResponse


def htmx_payment_success(message, payment_id=None):
    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps({
        "showNotification": {
            "message": message,
            "level": "success",
        },
        "paymentSuccess": {
            "payment_id": payment_id,
        }
    })
    return response


def htmx_payment_failure(message: object, errors: object = None) -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps({
        "showNotification": {
            "message": message,
            "level": "error",
        },
        "paymentFailed": {
            "message": message,
            "errors": errors or {},
        }
    })
    return response