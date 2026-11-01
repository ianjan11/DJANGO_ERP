"""
Reordering rule (stock.warehouse.orderpoint).

It only DETECTS a shortage and raises a Procurement; routes and ProcurementGroup.run() decide how
the goods arrive. Quantities are in the product's storage UoM (Product.uom), like StockQuant.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Callable

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

ZERO = Decimal("0")
DEC = DecimalField(max_digits=28, decimal_places=8)

# Move quantity is in move.product_uom; convert to the storage UoM in SQL, mirroring Uom.convert_to:
#   qty / from.factor * to.factor
STORAGE_QTY = ExpressionWrapper(
    F("quantity") * F("product__uom__factor")
    / Coalesce(F("product_uom__factor"), F("product__uom__factor")),
    output_field=DEC,
)

# Supply apps register quantities that are "on their way" but not stock moves yet (draft RFQ lines,
# planned manufacturing orders). Without this a rule reorders on every run until the PO is confirmed.
#   source(rule, horizon) -> Decimal in storage UoM
FORECAST_SOURCES: list[Callable] = []


def register_forecast_source(fn):
    FORECAST_SOURCES.append(fn)
    return fn


@dataclass
class ReorderingResult:
    ordered: list = field(default_factory=list)   # [(rule, qty)]
    skipped: int = 0                              # forecast is healthy
    errors: list = field(default_factory=list)    # [(rule, message)]


class ReorderRule(models.Model):

    class Trigger(models.TextChoices):
        AUTO = "auto", "Auto (scheduler orders it)"
        MANUAL = "manual", "Manual (suggest only)"

    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE, related_name="reorder_rules")
    # Usually warehouse.lot_stock. With multi-step reception put the rule on the warehouse view
    # location instead, so stock waiting in Input is inside the forecast subtree.
    location = models.ForeignKey("inventory.StockLocation", on_delete=models.CASCADE, related_name="reorder_rules")
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name="reorder_rules")

    min_qty = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO,
                                  help_text="Order when forecast stock falls below this.")
    max_qty = models.DecimalField(max_digits=14, decimal_places=3, default=ZERO,
                                  help_text="Order enough to bring forecast stock up to this.")
    qty_multiple = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("1"),
                                       help_text="Order quantity is rounded UP to a multiple of this.")
    visibility_days = models.PositiveIntegerField(
        default=0, help_text="Look-ahead window: moves due inside it count, and the demand is dated at its end.")
    route = models.ForeignKey("inventory.StockRoute", null=True, blank=True, on_delete=models.SET_NULL,
                              help_text="Optional: force this route when replenishing.")
    trigger = models.CharField(max_length=10, choices=Trigger.choices, default=Trigger.AUTO)
    active = models.BooleanField(default=True)

    last_run_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.TextField(blank=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(min_qty__gte=0), name="rr_min_nonneg"),
            models.CheckConstraint(condition=Q(max_qty__gte=F("min_qty")), name="rr_max_gte_min"),
            models.CheckConstraint(condition=Q(qty_multiple__gt=0), name="rr_multiple_pos"),
            models.UniqueConstraint(fields=["product", "location"], condition=Q(active=True),
                                    name="uniq_active_rr_product_location"),
        ]
        indexes = [models.Index(fields=["company", "trigger", "active"], name="rr_scheduler_lookup")]

    def __str__(self):
        return f"{self.product} @ {self.location} [{self.min_qty}-{self.max_qty}]"

    @property
    def warehouse(self):
        """Derived from the location tree, so it can never disagree with the location."""
        return self.location.warehouse

    def clean(self):
        super().clean()
        if self.min_qty > self.max_qty:
            raise ValidationError("Minimum quantity cannot exceed maximum quantity.")
        if self.product.product_type != "storable":
            raise ValidationError("Only storable products can have a reordering rule.")
        if self.location.usage != self.location.Usage.INTERNAL:
            raise ValidationError("A reordering rule needs an internal location.")
        if self.location.company_id != self.company_id or self.product.company_id != self.company_id:
            raise ValidationError("Product, location and rule must belong to the same company.")
        if self.route_id and self.route.company_id != self.company_id:
            raise ValidationError("Route must belong to the same company.")

    # ------------------------------------------------------------------ forecast
    def horizon(self, now=None) -> datetime:
        return (now or timezone.now()) + timedelta(days=self.visibility_days)

    def forecast_qty(self, now=None) -> Decimal:
        """on hand + incoming - outgoing (+ registered sources) over the location's subtree.

        * on hand: every quant in the subtree. Reserved quantity is NOT subtracted: the confirmed
          moves that hold the reservation are already counted as outgoing.
        * incoming/outgoing: confirmed moves (waiting, confirmed, partially available, assigned)
          due inside the window (no date = due now) that cross the subtree boundary. Draft moves
          are not committed yet. Because push moves are created at confirmation, goods still
          travelling through Input already show up as incoming to Stock."""
        from django.apps import apps
        StockQuant = apps.get_model("inventory", "StockQuant")
        StockMove = apps.get_model("inventory", "StockMove")

        ids = list(self.location.descendants(include_self=True).values_list("id", flat=True))
        horizon = self.horizon(now)

        on_hand = StockQuant.objects.filter(product=self.product, location_id__in=ids).aggregate(
            q=Coalesce(Sum("quantity"), Value(ZERO, output_field=DEC), output_field=DEC))["q"]

        moves = (StockMove.objects.filter(product=self.product, status__in=StockMove.ACTIVE_STATUSES)
                 .filter(Q(date__lte=horizon)))
        total = Coalesce(Sum(STORAGE_QTY), Value(ZERO, output_field=DEC), output_field=DEC)
        incoming = (moves.filter(dest_location_id__in=ids).exclude(source_location_id__in=ids)
                    .aggregate(q=total)["q"])
        outgoing = (moves.filter(source_location_id__in=ids).exclude(dest_location_id__in=ids)
                    .aggregate(q=total)["q"])

        extra = sum((src(self, horizon) for src in FORECAST_SOURCES), ZERO)
        return on_hand + incoming - outgoing + extra

    def qty_to_order(self, forecast=None, now=None) -> Decimal:
        forecast = self.forecast_qty(now) if forecast is None else forecast
        if forecast >= self.min_qty:
            return ZERO
        need = self.max_qty - forecast
        return (need / self.qty_multiple).to_integral_value(rounding=ROUND_CEILING) * self.qty_multiple

    # ------------------------------------------------------------------ procurement
    def _prepare_procurement(self, qty, group, now=None):
        from inventory.models.procurement_group import Procurement
        return Procurement(
            product=self.product, quantity=qty, uom=self.product.uom, location=self.location,
            name=f"RR/{self.pk}", origin=f"RR/{self.pk}", company=self.company,
            values={"group": group, "date_planned": self.horizon(now),
                    "route_ids": [self.route] if self.route_id else [],
                    "warehouse": self.warehouse, "company": self.company},
        )

    @classmethod
    def procure_orderpoint_confirm(cls, company, *, location=None, rules=None, include_manual=False, now=None):
        """Odoo's _procure_orderpoint_confirm: evaluate rules, raise a procurement for each one below
        minimum. One savepoint per rule, so a rule with a missing route doesn't block the others; its
        error is stored on the rule. Idempotent (orders show up as incoming in the next forecast) and
        concurrency-safe (rows locked with skip_locked)."""
        from inventory.models import ProcurementGroup
        from inventory.models.procurement_group import ProcurementException

        now = now or timezone.now()
        result = ReorderingResult()
        qs = rules if rules is not None else cls.objects.filter(company=company, active=True)
        if location is not None:
            qs = qs.filter(location__in=location.descendants(include_self=True))
        if not include_manual:
            qs = qs.filter(trigger=cls.Trigger.AUTO)

        with transaction.atomic():
            locked = list(qs.select_related("product", "location", "location__warehouse", "route")
                            .select_for_update(skip_locked=True, of=("self",)))
            group = None
            for rule in locked:
                rule.last_run_at = now
                qty = rule.qty_to_order(now=now)
                if qty <= 0:
                    result.skipped += 1
                    rule.last_error = ""
                    continue
                if group is None:     # one group per run: receipts of the run merge into one picking
                    group = ProcurementGroup.objects.create(name=f"Reordering {now:%Y-%m-%d %H:%M}",
                                                            company=company)
                try:
                    with transaction.atomic():
                        ProcurementGroup.run([rule._prepare_procurement(qty, group, now)])
                except ProcurementException as e:
                    rule.last_error = "; ".join(m for _p, m in e.procurement_exceptions)
                    result.errors.append((rule, rule.last_error))
                else:
                    rule.last_error = ""
                    result.ordered.append((rule, qty))
            cls.objects.bulk_update(locked, ["last_run_at", "last_error"])
        return result

    @classmethod
    def suggest_orders(cls, company, *, now=None):
        """Dry run: [(rule, forecast, qty_to_order)] for rules below minimum. Orders nothing."""
        now = now or timezone.now()
        out = []
        for rule in cls.objects.filter(company=company, active=True).select_related("product", "location"):
            forecast = rule.forecast_qty(now)
            qty = rule.qty_to_order(forecast, now)
            if qty > 0:
                out.append((rule, forecast, qty))
        return out