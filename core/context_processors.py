import logging
from django.urls import reverse, NoReverseMatch
from django.utils.text import slugify
from .navigation import NAVIGATION

logger = logging.getLogger(__name__)


def active_company(request):
    user = getattr(request, "user", None)

    if user and user.is_authenticated:
        # Query active companies via the active CompanyMembership relation
        user_companies = [
            membership.company
            for membership in user.company_memberships.filter(
                is_active=True,
                company__is_active=True
            ).select_related("company")
        ]
    else:
        user_companies = []

    return {
        "active_company": getattr(request, "company", None),
        "user_companies": user_companies,
    }


def _resolve_link(item, target, current_names):
    url_name = item.get("url")
    if not url_name:
        logger.debug("Nav item skipped (no URL key): %s", item.get("label"))
        return None

    try:
        href = reverse(url_name)
    except NoReverseMatch:
        logger.debug("Nav item skipped (failed reverse): %s -> %s", item.get("label"), url_name)
        return None

    active_urls = {url_name, *item.get("also_active", [])}

    return {
        **item,
        "href": href,
        "target": item.get("target", target),
        "is_active": bool(current_names & active_urls),
    }


def _resolve_item(item, target, current_names):
    if "sections" not in item:  # Plain link
        return _resolve_link(item, target, current_names)

    sections = []  # Dropdown / Mega Menu
    for section in item["sections"]:
        links = [
            link for link in (_resolve_link(i, target, current_names) for i in section.get("items", []))
            if link is not None
        ]
        if links:
            sections.append({**section, "items": links})

    if not sections:  # Omit empty dropdowns
        return None

    return {
        **item,
        "key": item.get("key") or slugify(item["label"]),
        "sections": sections,
        "is_active": any(link["is_active"] for section in sections for link in section["items"]),
    }


def app_navigation(request):
    match = getattr(request, "resolver_match", None)
    if not match:
        return {"nav_items": [], "nav_target": "body"}

    current_app = match.app_name or (match.namespaces[0] if match.namespaces else None)

    # 1. Match navigation config by main app key or alternative namespaces
    config = None
    if current_app in NAVIGATION:
        config = NAVIGATION[current_app]
    else:
        for app_key, app_config in NAVIGATION.items():
            if current_app in app_config.get("namespaces", []):
                config = app_config
                break

    if not config:
        return {"nav_items": [], "nav_target": "body"}

    target = config.get("target", "body")

    # 2. Build set of matching identifiers (view_name, app:url_name)
    current_names = set()
    if match.view_name:
        current_names.add(match.view_name)
    if match.app_name and match.url_name:
        current_names.add(f"{match.app_name}:{match.url_name}")

    # 3. Resolve navigation items
    nav_items = [
        resolved
        for resolved in (_resolve_item(item, target, current_names) for item in config.get("items", []))
        if resolved is not None
    ]

    return {"nav_items": nav_items, "nav_target": target}