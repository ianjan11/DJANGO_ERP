"""
Routes and rules (stock.route / stock.rule / stock.warehouse.orderpoint structure).

  StockRoute        named bundle of rules; RouteAssignment says where it applies
  StockRule         movement rule, action PULL or PUSH (no combined pull_push: use two rules)
                    PULL creates a move when demand appears at location_dest
                    PUSH creates a follow-up when a move is confirmed INTO location_src
  SupplyRule        buy / manufacture: how stock enters the network (handlers are registered)
"""
from datetime import timedelta
from dataclasses import replace
from typing import Callable

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _


class StockRoute(models.Model):
    name = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    sequence = models.PositiveIntegerField(default=10)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name="stock_routes")

    class Meta:
        ordering = ["sequence", "name"]
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="uniq_route_company_name")]

    def __str__(self):
        return self.name


class RouteAssignment(models.Model):
    """Attaches a route to exactly one target. Replaces Odoo's selectable_on_* flags and makes
    precedence explicit: product > category (nearest ancestor first) > warehouse."""

    class Scope(models.TextChoices):
        PRODUCT = "product", _("Product")
        CATEGORY = "category", _("Category")
        WAREHOUSE = "warehouse", _("Warehouse")

    route = models.ForeignKey(StockRoute, on_delete=models.CASCADE, related_name="assignments")
    scope = models.CharField(max_length=20, choices=Scope.choices)
    product = models.ForeignKey("inventory.Product", null=True, blank=True, on_delete=models.CASCADE)
    category = models.ForeignKey("inventory.ProductsCategory", null=True, blank=True, on_delete=models.CASCADE)
    warehouse = models.ForeignKey("inventory.Warehouse", null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="route_assignment_single_target",
                condition=(
                    Q(scope="product", product__isnull=False, category__isnull=True, warehouse__isnull=True)
                    | Q(scope="category", category__isnull=False, product__isnull=True, warehouse__isnull=True)
                    | Q(scope="warehouse", warehouse__isnull=False, product__isnull=True, category__isnull=True)
                ),
            ),
        ]


class StockRule(models.Model):

    class Action(models.TextChoices):
        PULL = "pull", _("Pull From (demand driven)")
        PUSH = "push", _("Push To (when a move is confirmed)")

    class ProcureMethod(models.TextChoices):
        MAKE_TO_STOCK = "make_to_stock", _("Take From Stock")
        MAKE_TO_ORDER = "make_to_order", _("Trigger Another Rule (MTO)")

    class Auto(models.TextChoices):
        MANUAL = "manual", _("Manual Operation (adds a step)")
        TRANSPARENT = "transparent", _("Automatic, No Step Added")

    class GroupPropagation(models.TextChoices):
        NONE = "none", _("Leave Empty")
        PROPAGATE = "propagate", _("Propagate")
        FIXED = "fixed", _("Fixed")

    name = models.CharField(max_length=150)
    action = models.CharField(max_length=10, choices=Action.choices)
    route = models.ForeignKey(StockRoute, on_delete=models.CASCADE, related_name="rules")
    sequence = models.PositiveIntegerField(default=10)
    active = models.BooleanField(default=True)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name="stock_rules")

    picking_type = models.ForeignKey("inventory.StockPickingType", on_delete=models.PROTECT,
                                     related_name="stock_rules")
    location_src = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT,
                                     related_name="rules_as_source")
    location_dest = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT,
                                      related_name="rules_as_dest")

    procure_method = models.CharField(max_length=20, choices=ProcureMethod.choices,
                                      default=ProcureMethod.MAKE_TO_STOCK)       # pull only
    auto = models.CharField(max_length=12, choices=Auto.choices, blank=True, default="")  # push only

    group_propagation_option = models.CharField(max_length=10, choices=GroupPropagation.choices,
                                                default=GroupPropagation.PROPAGATE)
    group = models.ForeignKey("inventory.ProcurementGroup", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    warehouse = models.ForeignKey("inventory.Warehouse", null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+",
                                  help_text="Warehouse to consider for the next procurement.")
    delay = models.PositiveIntegerField(default=0, help_text="Days this step takes.")
    propagate_cancel = models.BooleanField(default=False)
    propagate_partner = models.BooleanField(default=True)

    # Optional narrowing (null = any)
    only_category = models.ForeignKey("inventory.ProductsCategory", null=True, blank=True,
                                      on_delete=models.CASCADE, related_name="+")
    only_product = models.ForeignKey("inventory.Product", null=True, blank=True,
                                     on_delete=models.CASCADE, related_name="+")
    # Set on rules generated by a warehouse (Warehouse._sync_routes), so they can be updated in place.
    system_key = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        ordering = ["route__sequence", "sequence", "id"]
        constraints = [
            models.CheckConstraint(name="rule_src_ne_dest", condition=~Q(location_src=F("location_dest"))),
            models.CheckConstraint(
                name="rule_action_fields",
                condition=(Q(action="pull", auto="")
                           | Q(action="push", auto__in=["manual", "transparent"], procure_method="make_to_stock")),
            ),
            models.CheckConstraint(
                name="rule_fixed_group_needs_group",
                condition=~Q(group_propagation_option="fixed") | Q(group__isnull=False),
            ),
            models.UniqueConstraint(fields=["route", "system_key"], condition=~Q(system_key=""),
                                    name="uniq_rule_route_system_key"),
        ]
        indexes = [
            models.Index(fields=["action", "location_dest", "active"], name="rule_pull_lookup"),
            models.Index(fields=["action", "location_src", "active"], name="rule_push_lookup"),
        ]

    def __str__(self):
        return f"{self.name} [{self.get_action_display()}]: {self.location_src} → {self.location_dest}"

    def clean(self):
        super().clean()
        if self.action == self.Action.PUSH and not self.auto:
            self.auto = self.Auto.MANUAL
        if self.route_id and self.company_id and self.route.company_id != self.company_id:
            raise ValidationError(_("Rule and route must belong to the same company."))
        if self.only_product_id and self.only_category_id:
            raise ValidationError(_("Restrict by product or category, not both."))

    def matches(self, product):
        if self.only_product_id:
            return self.only_product_id == product.id
        if self.only_category_id:
            return self.only_category_id == product.category_id
        return True

    # ------------------------------------------------------------------ pull
    def _get_stock_move_values(self, p):
        """Odoo's _get_stock_move_values: the draft move a pull rule creates for a procurement."""
        from inventory.models import StockLocation, StockMove

        v = p.values
        group = None
        if self.group_propagation_option == self.GroupPropagation.PROPAGATE:
            group = v.get("group")
        elif self.group_propagation_option == self.GroupPropagation.FIXED:
            group = self.group
        # sale_line only on the move that reaches the customer: your invoicing counts delivered
        # quantity from moves, so putting it on pick/pack/ship would count it once per step.
        to_customer = self.location_dest.usage == StockLocation.Usage.CUSTOMER
        return dict(
            product=p.product, quantity=p.quantity, product_uom=p.uom, packaging=v.get("packaging"),
            source_location=self.location_src, dest_location=self.location_dest,
            picking_type=self.picking_type, group=group, rule=self, origin=(p.origin or "")[:64],
            warehouse=self.warehouse or v.get("warehouse"),
            partner=v.get("partner") if self.propagate_partner else None,
            date=v["date_planned"] - timedelta(days=self.delay),
            procure_method=self.procure_method, propagate_cancel=self.propagate_cancel,
            company=p.company, sale_line=v.get("sale_line") if to_customer else None,
            status=StockMove.Status.DRAFT,
        )

    @classmethod
    def _run_pull(cls, procurements):
        """Create the moves, then confirm them as a batch (Odoo: create(...)._action_confirm()).
        Chaining is not done here: an MTO move asks its source location for supply when it is confirmed."""
        from inventory.models import StockMove
        from inventory.models.procurement_group import ProcurementException

        created, errors = [], []
        for p, rule in procurements:
            try:
                with transaction.atomic():
                    move = StockMove.objects.create(**rule._get_stock_move_values(p))
                    move.routes.set(p.values.get("route_ids") or [])
                    move.move_dest_ids.set(p.values.get("move_dest_ids") or [])
            except ValidationError as e:
                errors.append((p, "; ".join(e.messages)))
                continue
            created.append(move.pk)
        if errors:
            raise ProcurementException(errors)
        StockMove.objects.filter(pk__in=created).action_confirm()

    # ------------------------------------------------------------------ push
    def _run_push(self, move, visited):
        """Odoo's _run_push, called from StockMove queryset push_apply().
        TRANSPARENT: redirect the move itself, no new step.
        MANUAL: a new move that waits for `move` (make_to_order + move_dest link)."""
        from inventory.models import StockMove

        new_date = move.date + timedelta(days=self.delay)
        if self.auto == self.Auto.TRANSPARENT:
            old_dest = move.dest_location_id
            move.dest_location = self.location_dest
            move.date = new_date
            move.save(update_fields=["dest_location", "date"])
            if self.location_dest_id != old_dest:        # is another step defined from here?
                StockMove.objects.filter(pk=move.pk).push_apply(visited)
            return None

        new = StockMove.objects.create(
            product=move.product, quantity=move.quantity, product_uom=move.product_uom,
            packaging=move.packaging,
            source_location=move.dest_location, dest_location=self.location_dest,
            picking_type=self.picking_type, group=move.group, rule=self,
            origin=move.origin or (move.picking.name if move.picking_id else ""),
            warehouse=self.warehouse, partner=move.partner if self.propagate_partner else None,
            date=new_date, procure_method=StockMove.ProcureMethod.MAKE_TO_ORDER,
            propagate_cancel=self.propagate_cancel, company=move.company,
            status=StockMove.Status.DRAFT,
        )
        new.routes.set(move.routes.all())
        move.move_dest_ids.add(new)
        return new


class SupplyRule(models.Model):
    """Buy / Manufacture. Kept apart from StockRule: these are not location-to-location moves."""

    class Action(models.TextChoices):
        BUY = "buy", _("Buy")
        MANUFACTURE = "manufacture", _("Manufacture")

    route = models.ForeignKey(StockRoute, on_delete=models.CASCADE, related_name="supply_rules")
    action = models.CharField(max_length=20, choices=Action.choices)
    location_dest = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="+")
    picking_type = models.ForeignKey("inventory.StockPickingType", on_delete=models.PROTECT, related_name="+")
    sequence = models.PositiveIntegerField(default=10)
    delay = models.PositiveIntegerField(default=0)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name="+")
    system_key = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["route", "system_key"], condition=~Q(system_key=""),
                                    name="uniq_supply_rule_route_system_key"),
        ]

    @classmethod
    def _run(cls, action, procurements):
        """Odoo's _run_buy / _run_manufacture: dispatch to the handler the purchase / manufacturing
        app registered. The planned date is already shifted by the rule's delay."""
        from inventory.models.procurement_group import ProcurementException

        handler = SUPPLY_HANDLERS.get(action)
        if handler is None:
            raise ProcurementException(
                [(p, f"No handler registered for supply action '{action}'.") for p, _r in procurements])
        handler([
            (replace(p, values={**p.values, "date_planned": p.values["date_planned"] - timedelta(days=rule.delay)}),
             rule)
            for p, rule in procurements
        ])


# handler(procurements: list[(Procurement, SupplyRule)]) -> None
#   BUY: create or merge draft PO lines; keep p.values["move_dest_ids"], ["group"] and the rule on the
#   line so receipt moves created when the PO is confirmed get move_dest_ids / group / rule.
SUPPLY_HANDLERS: dict[str, Callable] = {}


def register_supply_handler(action: str):
    def deco(fn):
        SUPPLY_HANDLERS[action] = fn
        return fn
    return deco


# ----------------------------------------------------------------------
# Route resolution
# ----------------------------------------------------------------------
SCOPE_PRECEDENCE = ["product", "category", "warehouse"]     # most specific first


def routes_for(product, warehouse=None, route_ids=()):
    """Routes in precedence order: forced routes (e.g. from a sales line), then product, category
    (nearest ancestor first, as Odoo's parent_path lookup), then warehouse. Ties: route sequence."""
    cat_ids, cat = [], product.category
    while cat is not None:
        cat_ids.append(cat.pk)
        cat = cat.parent

    cond = Q(scope="product", product=product) | Q(scope="category", category_id__in=cat_ids)
    if warehouse is not None:
        cond |= Q(scope="warehouse", warehouse=warehouse)
    assignments = RouteAssignment.objects.filter(route__active=True).filter(cond).select_related("route")

    def key(a):
        depth = cat_ids.index(a.category_id) if a.scope == "category" else 0
        return (SCOPE_PRECEDENCE.index(a.scope), depth, a.route.sequence, a.route_id)

    seen = set()
    for route in route_ids:
        if route.active and route.pk not in seen:
            seen.add(route.pk)
            yield route
    for a in sorted(assignments, key=key):
        if a.route_id not in seen:
            seen.add(a.route_id)
            yield a.route


def find_push_rule(product, location, warehouse, company, route_ids=()):
    """First matching push rule for a move arriving AT `location`."""
    for route in routes_for(product, warehouse, route_ids):
        for rule in route.rules.filter(action=StockRule.Action.PUSH, location_src=location,
                                       company=company, active=True):
            if rule.matches(product):
                return rule
    return None