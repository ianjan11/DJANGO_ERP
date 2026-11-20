from urllib.parse import urlencode

from django import template
from django.urls import reverse, NoReverseMatch

register = template.Library()

# ---------------------------------------------------------------------------
# Settings map — same idea as NAVIGATION: add a row here and it appears.
# Rows whose URL name does not reverse are skipped silently, so you can
# list pages before they exist.
#   accent : any CSS color; tints the icon tiles of that section
#   module : sent as ?module=… (your partner views read it)
# ---------------------------------------------------------------------------
SETTINGS_SECTIONS = [

    {
        "key": "company",
        "label": "Company",
        "description": "Your business profile, fiscal period and who can access it.",
        "icon": "building-gear",
        "accent": "var(--color-sky-blue, #7ea7e9)",
        "items": [
            {"label": "Companies", "description": "Your business profiles and organization details.",
             "icon": "buildings", "url": "core:company_list", "module": "settings"},
            {"label": "Fiscal year & lock dates",
             "description": "Fiscal start month and the accounting and tax lock dates.",
             "icon": "calendar-range", "url": "core:company_settings", "module": "settings"},
            {"label": "Tenants & users", "description": "People with access to this company and their roles.",
             "icon": "person-gear", "url": "core:tenant_user_list", "module": "settings"},
        ],
    },

    {
        "key": "contacts",
        "label": "Contacts",
        "description": "The customers and suppliers you trade with.",
        "icon": "people",
        "accent": "var(--color-forest-teal)",
        "items": [
            {"label": "Customers", "description": "People and companies you sell to, with their payment terms and receivable accounts.",
             "icon": "person-lines-fill", "url": "core:customers", "module": "settings"},
            {"label": "Suppliers", "description": "Vendors you buy from, with their payment terms and payable accounts.",
             "icon": "truck", "url": "core:vendors", "module": "settings"},
        ],
    },
    {
        "key": "accounting",
        "label": "Accounting",
        "description": "How money is recorded, taxed and converted.",
        "icon": "journal-text",
        "accent": "var(--color-lavender)",
        "items": [
            {"label": "Chart of accounts", "description": "Every account your entries post to, grouped by type.",
             "icon": "diagram-3", "url": "accounting:accounts_list", "module": "settings"},
            {"label": "Journals", "description": "Bank, cash and general journals with their numbering.",
             "icon": "journals", "url": "accounting:journals_list", "module": "settings"},
            {"label": "Taxes", "description": "Tax rates applied to invoice and order lines.",
             "icon": "percent", "url": "accounting:taxes_list", "module": "settings"},
            {"label": "Currencies", "description": "Active currencies and their exchange rates.",
             "icon": "currency-exchange", "url": "accounting:currency_view", "module": "settings"},
            {"label": "Payment terms", "description": "Due-date rules such as Net 30 or 50% upfront.",
             "icon": "calendar-check", "url": "accounting:payment_terms_list", "module": "settings"},
        ],
    },
    {
        "key": "inventory",
        "label": "Inventory",
        "description": "Where stock lives and how it is organised.",
        "icon": "boxes",
        "accent": "var(--color-ember-orange)",
        "items": [
            {"label": "Warehouses", "description": "Physical sites that hold and ship your stock.",
             "icon": "building", "url": "inventory:warehouse_list", "module": "settings"},
            {"label": "Locations", "description": "Shelves, bins and zones inside each warehouse.",
             "icon": "geo-alt", "url": "inventory:locations_list", "module": "settings"},
            {"label": "Product categories", "description": "Groups that drive reporting and default accounts.",
             "icon": "tags-fill", "url": "inventory:view_categories", "module": "settings"},
        ],
    },
]


def _resolve(item):
    try:
        href = reverse(item["url"])
    except NoReverseMatch:
        return None
    if item.get("module"):
        href = f"{href}?{urlencode({'module': item['module']})}"
    return {**item, "href": href}


@register.simple_tag
def settings_sections():
    sections = []
    for section in SETTINGS_SECTIONS:
        items = [i for i in (_resolve(x) for x in section["items"]) if i]
        if items:
            sections.append({**section, "items": items})
    return sections