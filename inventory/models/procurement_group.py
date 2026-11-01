"""
procurement.group: the group that ties together every move/picking created for one demand,
and (as in Odoo) the entry point of the procurement engine: ProcurementGroup.run().

    Procurement(...)  ->  ProcurementGroup.run([...])
        -> _get_rule()                         route precedence, pull rules, then supply rules
        -> StockRule._run_pull(items)          creates moves, then action_confirm() on them
              -> StockMove.action_confirm()    MTO moves run ProcurementGroup.run() upstream (chain),
                                               then push rules, then picking assignment
        -> SupplyRule._run(action, items)      buy / manufacture handlers
"""
import contextvars
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

MAX_PROCUREMENT_DEPTH = 10
_depth = contextvars.ContextVar("procurement_depth", default=0)   # loop guard for MTO chains


@dataclass
class Procurement:
    """Odoo's procurement.group.Procurement: replenish `quantity` of `product` at `location`.

    values (same keys as Odoo): group, date_planned, route_ids, warehouse, partner,
    move_dest_ids, sale_line, packaging, company.
    `warehouse` is required when `location` has none (e.g. the Customers location of a sales order).
    """
    product: object
    quantity: Decimal               # in `uom`
    uom: object
    location: object
    name: str
    origin: str
    company: object
    values: dict = field(default_factory=dict)


class ProcurementException(Exception):
    def __init__(self, procurement_exceptions):
        self.procurement_exceptions = procurement_exceptions    # [(Procurement, message)]
        super().__init__("\n".join(f"{p.product} @ {p.location}: {m}" for p, m in procurement_exceptions))


class ProcurementGroup(models.Model):

    class MoveType(models.TextChoices):
        DIRECT = "direct", "As soon as possible"
        ONE = "one", "When all products are ready"

    name = models.CharField(max_length=150)
    move_type = models.CharField(max_length=10, choices=MoveType.choices, default=MoveType.DIRECT)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE)
    partner = models.ForeignKey("core.Partner", null=True, blank=True, on_delete=models.SET_NULL)
    # Odoo: procurement.group.sale_id. Pickings of the demand pick their sales order up from here.
    sales_order = models.ForeignKey("sales.SalesOrder", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "inventory_procurement_group"
        verbose_name = "Procurement Group"
        verbose_name_plural = "Procurement Groups"

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------ rule lookup
    @classmethod
    def _get_rule(cls, product, location, values):
        """Odoo's _get_rule: walk routes in precedence order (forced routes from `values`, then
        product, category, warehouse). Inside a route a pull rule beats a supply rule."""
        from inventory.models.routes_and_rules import StockRule, routes_for

        company = values["company"]
        warehouse = values.get("warehouse") or location.warehouse
        for route in routes_for(product, warehouse, values.get("route_ids") or ()):
            for rule in route.rules.filter(action=StockRule.Action.PULL, location_dest=location,
                                           company=company, active=True):
                if rule.matches(product):
                    return rule
            supply = (route.supply_rules.filter(location_dest=location, company=company)
                      .order_by("sequence").first())
            if supply is not None:
                return supply
        return None

    # ------------------------------------------------------------------ engine
    @classmethod
    def run(cls, procurements):
        """Odoo's procurement.group.run. All-or-nothing: any error rolls back every move created
        by this call and raises ProcurementException listing all of them."""
        from inventory.models.routes_and_rules import StockRule, SupplyRule

        if not procurements:
            return
        depth = _depth.get()
        if depth >= MAX_PROCUREMENT_DEPTH:
            raise ProcurementException([(procurements[0], "Rule chain too deep (possible loop in the routes).")])

        token = _depth.set(depth + 1)
        try:
            with transaction.atomic():
                actions, errors = defaultdict(list), []
                for p in procurements:
                    p.values.setdefault("company", p.company)
                    p.values.setdefault("date_planned", timezone.now())
                    if not p.product.is_stockable or p.quantity <= 0:
                        continue                                    # services / empty demand do nothing
                    rule = cls._get_rule(p.product, p.location, p.values)
                    if rule is None:
                        errors.append((p, f'No rule has been found to replenish "{p.product}" in '
                                          f'"{p.location}". Verify the routes configuration.'))
                        continue
                    actions["pull" if isinstance(rule, StockRule) else rule.action].append((p, rule))
                if errors:
                    raise ProcurementException(errors)

                for action, items in actions.items():
                    try:
                        if action == "pull":
                            StockRule._run_pull(items)
                        else:
                            SupplyRule._run(action, items)
                    except ProcurementException as e:
                        errors += e.procurement_exceptions
                if errors:
                    raise ProcurementException(errors)
        finally:
            _depth.reset(token)

    @classmethod
    def run_scheduler(cls, company):
        """Odoo's run_scheduler: today it only runs the reordering rules."""
        from inventory.models import ReorderRule
        return ReorderRule.procure_orderpoint_confirm(company)