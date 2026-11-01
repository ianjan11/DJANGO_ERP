"""
inventory/services/reordering.py

Service entry points for reordering rules. The rule (forecast, order quantity) and the scheduler
loop (ReorderRule.procure_orderpoint_confirm) live in models/reorder_rule.py, as in Odoo; this
module adds what callers need around it: a warehouse filter, ordering a reviewed selection of
manual rules, and a cron entry point over all companies.

A rule only DETECTS a shortage and raises a procurement. How the goods arrive is decided by the
routes of the warehouse (pull chain, then buy / manufacture). Quantities are in the product's
storage UoM.
"""
from django.apps import apps

from inventory.models import ReorderRule
from inventory.models.reorder_rule import ReorderingResult, register_forecast_source  # noqa: F401  (re-export)


def run_reordering(company, *, warehouse=None, location=None, rules=None, include_manual=False, now=None):
    """Order what is below minimum. `warehouse` limits the run to that warehouse (its whole location
    tree). Idempotent and safe to run concurrently (see ReorderRule.procure_orderpoint_confirm)."""
    if warehouse is not None and location is None:
        location = warehouse.view_location
    return ReorderRule.procure_orderpoint_confirm(
        company, location=location, rules=rules, include_manual=include_manual, now=now)


def suggest_orders(company, *, warehouse=None, now=None):
    """Dry run: [(rule, forecast, qty_to_order)] for rules below minimum. Orders nothing."""
    suggestions = ReorderRule.suggest_orders(company, now=now)
    if warehouse is not None:
        suggestions = [s for s in suggestions
                       if s[0].warehouse is not None and s[0].warehouse.pk == warehouse.pk]
    return suggestions


def order_selected(company, rule_ids, *, now=None):
    """A planner reviewed the suggestions and picked rules: order exactly those, manual ones included."""
    rules = ReorderRule.objects.filter(company=company, active=True, pk__in=list(rule_ids))
    return run_reordering(company, rules=rules, include_manual=True, now=now)


def run_reordering_all(*, now=None):
    """Cron / Celery entry point: every company that has an active auto rule. Returns {company: result}."""
    Company = apps.get_model("core", "Company")
    companies = Company.objects.filter(
        reorder_rules__active=True, reorder_rules__trigger=ReorderRule.Trigger.AUTO).distinct()
    return {company: run_reordering(company, now=now) for company in companies}


def summarize(result: ReorderingResult) -> str:
    """One-line summary for logs."""
    return (f"ordered {len(result.ordered)}, skipped {result.skipped}, failed {len(result.errors)}"
            + "".join(f"\n  {rule}: {message}" for rule, message in result.errors))