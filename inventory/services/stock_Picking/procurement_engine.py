"""
inventory/services/procurement_engine.py

Application layer on top of the model-level engine. The engine itself lives in the models, as in
Odoo:

    ProcurementGroup.run()               rule lookup + dispatch        (models/procurement_group.py)
    StockRule._run_pull / _run_push      create moves                  (models/routes_and_rules.py)
    StockMove.objects...action_confirm() chain, push, pickings         (models/stock_move.py)

This module is what the sales app, the purchase app and the scheduler call, so they never touch
that plumbing:

    procure_delivery()   confirm a sales order: group + procurements + run + reserve
    receive_purchase()   confirm a purchase order: receipt moves in a PO group, confirmed
    run_each()           run procurements one by one; failures are returned, the rest is kept
    reserve_pending()    reserve moves that are waiting for availability (cron)
    make_procurement(), get_or_create_group(), reserve_group()   building blocks

Supply handlers (buy / manufacture) and forecast sources are registered with the decorators
re-exported at the bottom.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inventory.models import ProcurementGroup, StockMove, StockPicking
from inventory.models.procurement_group import Procurement, ProcurementException
from inventory.models.reorder_rule import register_forecast_source  # noqa: F401  (re-export)
from inventory.models.routes_and_rules import register_supply_handler  # noqa: F401  (re-export)


# ---------------------------------------------------------------------- input / output shapes
@dataclass
class DemandLine:
    """One line of a sales order, as the procurement layer needs it."""
    product: object
    quantity: Decimal                      # in `uom`
    uom: object           # default: the product's storage UoM
    sale_line: Optional[object] = None     # lands on the move that reaches the customer
    packaging: Optional[object] = None
    route_ids: tuple = ()                  # forced routes for this line


@dataclass
class ReceiptLine:
    """One line of a purchase order."""
    product: object
    quantity: Decimal                      # in `uom` (the purchase UoM)
    uom: Optional[object] = None
    purchase_line: Optional[object] = None
    move_dest_ids: tuple = ()              # moves this receipt feeds (set by the buy handler)
    date: Optional[object] = None


@dataclass
class DeliveryResult:
    group: ProcurementGroup
    shortages: dict = field(default_factory=dict)   # {move: quantity that could not be reserved}


@dataclass
class ReceiptResult:
    group: ProcurementGroup
    moves: list = field(default_factory=list)
    pickings: list = field(default_factory=list)


# ---------------------------------------------------------------------- building blocks
def get_or_create_group(name, company, *, partner=None, sales_order=None,
                        move_type=ProcurementGroup.MoveType.DIRECT):
    """One group per order. Confirming the same order again reuses it, so extra quantity merges
    into the open pickings."""
    group = ProcurementGroup.objects.filter(name=name, company=company).first()
    return group or ProcurementGroup.objects.create(
        name=name, company=company, partner=partner, sales_order=sales_order, move_type=move_type)


def make_procurement(product, quantity, location, company, date_planned, *, warehouse=None, uom=None,
                     origin="", name=None, group=None, partner=None, sale_line=None, packaging=None,
                     route_ids=()):
    """Build a Procurement with the `values` keys the engine reads."""
    return Procurement(
        product=product, quantity=quantity, uom=uom or product.uom, location=location,
        name=name or origin or "/", origin=origin, company=company,
        values={"group": group, "date_planned": date_planned or timezone.now(),
                "warehouse": warehouse, "partner": partner, "sale_line": sale_line,
                "packaging": packaging, "route_ids": _as_routes(route_ids), "company": company})


def customer_location(warehouse):
    """The shared Customers location, taken from the warehouse's delivery type."""
    if warehouse.out_type_id is None:
        raise ValueError(f'Warehouse "{warehouse}" has no delivery type yet: '
                         'run warehouse._sync_picking_types() and warehouse._sync_routes().')
    return warehouse.out_type.default_dest_location


def reserve_group(group, *, allow_break=False):
    """action_assign() on every open picking of the group. Returns {move: shortage}."""
    shortages = {}
    open_pickings = group.pickings.exclude(
        status__in=[StockPicking.Status.COMPLETED, StockPicking.Status.CANCELLED]).order_by("id")
    for picking in open_pickings:
        shortages.update(picking.action_assign(allow_break=allow_break))
    return shortages


# ---------------------------------------------------------------------- sales
@transaction.atomic
def procure_delivery(*, name, company, warehouse, lines, date_planned, partner=None, sales_order=None,
                     move_type=ProcurementGroup.MoveType.DIRECT, reserve=True):
    """Confirm a sales order.

    One procurement per line, demanded at the Customers location; the warehouse's delivery route
    builds the pick / pack / ship chain. All or nothing: if any line has no rule a
    ProcurementException lists every failing line and nothing is created. Services are ignored by the
    engine. With reserve=True the new pickings try to reserve stock right away."""
    group = get_or_create_group(name, company, partner=partner, sales_order=sales_order,
                                move_type=move_type)
    customers = customer_location(warehouse)
    ProcurementGroup.run([
        make_procurement(l.product, l.quantity, customers, company, date_planned, warehouse=warehouse,
                         uom=l.uom, origin=name, group=group, partner=partner, sale_line=l.sale_line,
                         packaging=l.packaging, route_ids=l.route_ids)
        for l in lines])
    return DeliveryResult(group, reserve_group(group) if reserve else {})


# ---------------------------------------------------------------------- purchases
@transaction.atomic
def receive_purchase(*, name, company, warehouse, vendor, lines, purchase_order=None, date_planned=None):
    """Confirm a purchase order: one receipt move per stockable line, in a group of the PO itself
    (one PO = one receipt).

    * A line with move_dest_ids (the PO came from a shortage) feeds the waiting storage move, so no
      push rule fires.
    * A line without (hand-made PO) gets its next step from the push rules when it is confirmed.
    Receipt moves cancel along their chain (propagate_cancel)."""
    if warehouse.in_type_id is None:
        raise ValueError(f'Warehouse "{warehouse}" has no receipt type yet: '
                         'run warehouse._sync_picking_types() and warehouse._sync_routes().')
    in_type = warehouse.in_type
    group = get_or_create_group(name, company, partner=vendor)
    now = timezone.now()

    created = []
    for l in lines:
        if not l.product.is_stockable:
            continue
        move = StockMove.objects.create(
            product=l.product, quantity=l.quantity, product_uom=l.uom,
            source_location=in_type.default_source_location, dest_location=in_type.default_dest_location,
            picking_type=in_type, group=group, origin=name, company=company, warehouse=warehouse,
            partner=vendor, purchase_line=l.purchase_line, propagate_cancel=True,
            date=l.date or date_planned or now)
        if l.move_dest_ids:
            move.move_dest_ids.set(l.move_dest_ids)
        created.append(move.pk)

    StockMove.objects.filter(pk__in=created).action_confirm()
    pickings = list(StockPicking.objects.filter(moves__pk__in=created).distinct())
    if purchase_order is not None:
        for picking in pickings:
            if picking.purchase_order_id is None:
                picking.purchase_order = purchase_order
                picking.save(update_fields=["purchase_order"])
    return ReceiptResult(group, list(StockMove.objects.filter(pk__in=created)), pickings)


# ---------------------------------------------------------------------- scheduler helpers
def run_each(procurements):
    """Run procurements one by one, each in its own savepoint. ProcurementGroup.run() is all or
    nothing; this keeps the good ones and returns the failures as [(Procurement, message)]."""
    errors = []
    for p in procurements:
        try:
            with transaction.atomic():
                ProcurementGroup.run([p])
        except ProcurementException as e:
            errors += e.procurement_exceptions
    return errors


def reserve_pending(*, company=None, warehouse=None, batch=100):
    """Reserve moves that are waiting for availability, oldest first. Run it from cron: nothing else
    re-reserves a move when stock arrives later (only the moves a completed move feeds are retried).
    Returns {move: shortage}. Moves that already hold lines are left alone: topping up a partial
    reservation is up to your allocation engine."""
    S = StockMove.Status
    qs = StockMove.objects.filter(
        Q(status=S.CONFIRMED) | Q(status=S.WAITING, move_orig_ids__status=S.COMPLETED),
        lines__isnull=True)
    if company is not None:
        qs = qs.filter(company=company)
    if warehouse is not None:
        qs = qs.filter(source_location__warehouse=warehouse)
    ids = list(qs.distinct().order_by("date", "id").values_list("pk", flat=True))

    shortages = {}
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        shortages.update(StockMove.objects.filter(pk__in=chunk).order_by("date", "id").action_assign())
    return shortages


def _as_routes(route_ids):
    """Accept StockRoute objects or primary keys; routes_for() needs objects. Order is kept."""
    from inventory.models import StockRoute
    by_id = StockRoute.objects.in_bulk([r for r in route_ids if isinstance(r, int)])
    out = [by_id.get(r) if isinstance(r, int) else r for r in route_ids]
    return [r for r in out if r is not None]