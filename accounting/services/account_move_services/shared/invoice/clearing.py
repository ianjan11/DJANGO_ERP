# shared/clearing.py
"""
Single implementation of GDNI / GRNI clearing.

Open amounts come from PartialReconcile rows (the source of truth), never from
move.amount_residual, and one ClearingState per invoice stops two invoice lines
spending the same open entry.

kind "gdni":     open DEBIT on the delivery entry.
kind "grni":     open CREDIT on the receipt entry.
kind "gdni_ret": open CREDIT on the sales-return entry (cleared by the credit note).
kind "grni_ret": open DEBIT on the purchase-return entry (cleared by the vendor credit note).
"""
from collections import defaultdict
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, Sum

from accounting.models import AccountMove, AccountMoveLine, PartialReconcile
from accounting.services.account_move_services.shared.account_utils import round2
from inventory.models import StockMove

ZERO = Decimal("0.00")
CLEARING_ORIGINS = {
    "delivery": "gdni",          # open DEBIT on GDNI
    "receiving": "grni",         # open CREDIT on GRNI
    "sales_return": "gdni_ret",  # open CREDIT on GDNI (returned, already invoiced)
    "purchase_return": "grni_ret",  # open DEBIT on GRNI (returned, already billed)
}
DEBIT_OPEN = ("gdni", "grni_ret")   # kinds whose open item sits on the debit side


class ClearingState:
    """One per invoice build, shared across every invoice item."""

    def __init__(self):
        self.amount = defaultdict(Decimal)  # open entry pk  -> amount already spent
        self.qty = defaultdict(Decimal)     # order line pk  -> qty already cleared


def _d(value):
    return ZERO if value is None else Decimal(str(value))


# ---------------------------------------------------------------- linking

def source_ref(order_line):
    """kwargs that tie a GDNI/GRNI line to its sale/purchase order line
    (AccountMoveLine.source_line is a generic FK, so no migration needed)."""
    return {
        "source_line_type": ContentType.objects.get_for_model(order_line),
        "source_line_id": order_line.pk,
    }


# ---------------------------------------------------------------- open amounts

def line_open_amount(line, kind):
    if kind in DEBIT_OPEN:
        total, col = line.debit, "debit_line"
    else:
        total, col = line.credit, "credit_line"
    applied = (
        PartialReconcile.objects.filter(**{col: line}).aggregate(s=Sum("amount"))["s"]
        or ZERO
    )
    return round2(Decimal(total) - applied)


def open_total(entries, kind, state):
    return sum(
        (max(ZERO, line_open_amount(e, kind) - state.amount[e.pk]) for e in entries),
        ZERO,
    )


def allocate_open_entries(entries, amount, kind, state):
    """FIFO over `entries` (already ordered). Returns (allocations, total_open)."""
    remaining = Decimal(amount)
    allocations, total = [], ZERO
    for entry in entries:
        open_amt = line_open_amount(entry, kind) - state.amount[entry.pk]
        if open_amt <= ZERO:
            continue
        total += open_amt
        if remaining <= ZERO:
            continue
        applied = min(remaining, open_amt)
        allocations.append({"entry": entry, "amount": applied})
        state.amount[entry.pk] += applied
        remaining -= applied
    return allocations, total


# ---------------------------------------------------------------- quantities

def _move_qty(link_field, order_line, return_origin, returns, exclude_picking=None):
    """Storage-UoM qty of completed moves on an order line, split into normal
    movements vs return movements. A picking counts as a return once the returns
    module has valued it (AccountMove.origin_type == return_origin)."""
    return_pickings = AccountMove.objects.filter(
        origin_type=return_origin, origin_id__isnull=False
    ).values("origin_id")
    qs = StockMove.objects.filter(
        **{link_field: order_line}, status=StockMove.Status.COMPLETED
    ).prefetch_related("lines")
    qs = qs.filter(picking_id__in=return_pickings) if returns else qs.exclude(picking_id__in=return_pickings)
    if exclude_picking is not None:
        qs = qs.exclude(picking=exclude_picking)
    return sum((_d(l.quantity_in_storage_uom) for m in qs for l in m.lines.all()), ZERO)


def delivered_qty(sale_line, exclude_picking=None):
    """Qty delivered on a sale line (sales returns excluded)."""
    return _move_qty("sale_line", sale_line, "sales_return", False, exclude_picking)


def returned_sales_qty(sale_line):
    return _move_qty("sale_line", sale_line, "sales_return", True)


def received_qty(purchase_line, exclude_picking=None):
    """Qty received on a purchase line (purchase returns excluded)."""
    return _move_qty("purchase_line", purchase_line, "purchase_return", False, exclude_picking)


def returned_purchase_qty(purchase_line):
    return _move_qty("purchase_line", purchase_line, "purchase_return", True)


def netted_sales_return_qty(sale_line):
    """Returned units that came back BEFORE being invoiced: they were netted
    straight against the delivery's GDNI, so they no longer wait to be invoiced."""
    pool = max(ZERO, delivered_qty(sale_line) - invoiced_qty(sale_line, ("out_invoice",)))
    return min(returned_sales_qty(sale_line), pool)


def invoiced_qty(order_line, move_types, exclude_move=None):
    """Storage-UoM qty on POSTED product lines that point at this order line."""
    qs = AccountMoveLine.objects.filter(
        line_type=AccountMoveLine.LineType.PRODUCT,
        move__state=AccountMove.State.POSTED,
        move__move_type__in=move_types,
        **source_ref(order_line),
    ).select_related("product", "product_uom", "product__uom")
    if exclude_move is not None:
        qs = qs.exclude(move=exclude_move)
    return sum((_d(l.quantity_in_storage_uom) for l in qs), ZERO)


# ---------------------------------------------------------------- write-back

def _refresh_entry(entry, kind):
    """Recompute reconciled flag + move residual from PartialReconcile rows."""
    entry.reconciled = line_open_amount(entry, kind) <= ZERO
    AccountMoveLine.objects.filter(pk=entry.pk).update(reconciled=entry.reconciled)

    side = {"debit__gt": 0} if kind in DEBIT_OPEN else {"credit__gt": 0}
    siblings = AccountMoveLine.objects.filter(
        move_id=entry.move_id, account_id=entry.account_id, **side
    )
    residual = sum((line_open_amount(l, kind) for l in siblings), ZERO)
    AccountMove.objects.filter(pk=entry.move_id).update(
        amount_residual=max(ZERO, residual), reconciled=residual <= ZERO
    )


def apply_clearing(alloc, invoice_line, kind, user):
    """Call AFTER bulk_create so invoice_line has a pk."""
    pooled = alloc.get(f"{kind}_allocations") or []
    for ea in pooled:
        entry, applied = ea["entry"], round2(ea["amount"])
        if applied <= ZERO:
            continue
        # alloc side CREDIT => invoice line is the credit, entry is the debit
        debit_line, credit_line = (
            (entry, invoice_line) if alloc["side"] == "CREDIT" else (invoice_line, entry)
        )
        rec = PartialReconcile(
            debit_line=debit_line,
            credit_line=credit_line,
            amount=applied,
            amount_currency=ZERO,
            currency=None,
            created_by=user,
            company=entry.move.company,
        )
        rec.full_clean()
        rec.save()
        _refresh_entry(entry, kind)

    if pooled:
        # clearing leg equals the sum of its allocations by construction
        AccountMoveLine.objects.filter(pk=invoice_line.pk).update(reconciled=True)
        invoice_line.reconciled = True


def reverse_clearing(invoice):
    """Undo every GDNI/GRNI match made by this invoice.
    Call from cancel / reset-to-draft BEFORE the invoice lines are deleted."""
    own_ids = list(invoice.lines.values_list("pk", flat=True))
    origins = list(CLEARING_ORIGINS)
    recs = list(
        PartialReconcile.objects.filter(
            Q(debit_line_id__in=own_ids, credit_line__move__origin_type__in=origins)
            | Q(credit_line_id__in=own_ids, debit_line__move__origin_type__in=origins)
        ).select_related("debit_line__move", "credit_line__move")
    )
    entries, own_hit = [], []
    for r in recs:
        if r.debit_line_id in own_ids:
            own_hit.append(r.debit_line_id)
            entries.append(r.credit_line)
        else:
            own_hit.append(r.credit_line_id)
            entries.append(r.debit_line)

    PartialReconcile.objects.filter(pk__in=[r.pk for r in recs]).delete()
    AccountMoveLine.objects.filter(pk__in=own_hit).update(reconciled=False)
    seen = set()
    for e in entries:
        if e.pk in seen:
            continue
        seen.add(e.pk)
        _refresh_entry(e, CLEARING_ORIGINS[e.move.origin_type])