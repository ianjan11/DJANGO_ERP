import json
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
import json
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect


from django.core.exceptions import NON_FIELD_ERRORS


def _field_label(field, form=None):
    if field == NON_FIELD_ERRORS:
        return None
    if form is not None:
        try:
            return form.fields[field].label
        except KeyError:
            pass
    return field.replace("_", " ").capitalize()


def htmx_error(request, message, redirect_url=None, form=None, trigger=None):
    if isinstance(message, dict):
        lines = []
        for field, msgs in message.items():
            label = _field_label(field, form)
            for msg in msgs:
                lines.append(f"{label}: {msg}" if label else msg)
        text = " ".join(lines)
    elif isinstance(message, (list, tuple)):
        text = " ".join(str(m) for m in message)
    else:
        text = str(message)

    if request.headers.get("HX-Request"):

        payload = {
            "showNotification": {
                "message": text,
                "level": "error",
            }
        }

        if trigger:
            payload.update(trigger)

        response = HttpResponse(status=204)

        response["HX-Trigger"] = json.dumps(payload)
        return response

    messages.error(request, text)
    return redirect(redirect_url) if redirect_url else HttpResponse(status=400)


def htmx_success(
    request,
    message,
    trigger=None,
    redirect_url=None,
    target=None,
):
    if request.headers.get("HX-Request"):
        payload = {
            "showNotification": {
                "message": message,
                "level": "success",
            }
        }

        if trigger:
            payload.update(trigger)

        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps(payload)

        if redirect_url:
            response["HX-Location"] = json.dumps({
                "path": redirect_url,
                **({"target": target} if target else {}),
            })

        return response

    messages.success(request, message)

    if redirect_url:
        return redirect(redirect_url)

    return HttpResponse(status=200)

