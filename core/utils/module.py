from django.shortcuts import render

MODULE_BASE = {
    "sales":      "sales/base.html",
    "accounting": "accounting/base.html",
    "purchases":  "purchases/base.html",
    "settings":   "core/settings/base.html",
    "inventory": "core/inventory/base.html",
}

DEFAULT_MODULE = "settings"



def _module(request, default=DEFAULT_MODULE):
    """?module= wins (survives reload); then the HX-Target container id;
    then the caller's default."""
    module = request.GET.get("module")
    if not module:
        target = request.headers.get("HX-Target", "")
        module = target.removesuffix("-display")
    return module if module in MODULE_BASE else default


def _render(request, template, context, default_module=DEFAULT_MODULE):
    module = _module(request, default_module)
    context["module"] = module
    context["base_template"] = MODULE_BASE[module]

    response = render(request, template, context)

    if request.headers.get("HX-Request") and "module" not in request.GET:
        url = request.get_full_path()
        sep = "&" if "?" in url else "?"
        response["HX-Replace-Url"] = f"{url}{sep}module={module}"
    return response

def _validation_errors(exc):
    """Normalise a Django ValidationError into a dict of field -> messages."""
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"__all__": exc.messages}







