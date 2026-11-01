"""
Return valuation, separate from receipt (GRNI) and delivery (GDNI) valuation.

    create_valuation_for_sales_return(picking, user)     goods back FROM a customer
    create_valuation_for_purchase_return(picking, user)  goods sent back TO a supplier

The return flow must call these INSTEAD of create_valuation_for_incoming_picking /
create_valuation_for_picking for return pickings.

Each returned unit is either
  * NETTED   - it came back before the original document was invoiced/billed, so the
               delivery's open GDNI (receipt's open GRNI) is still open. The return
               cancels it immediately, at that entry's real cost, and reconciles it.
  * OPEN     - it was already invoiced/billed, so the invoice already moved the cost
               into COGS (cleared GRNI into AP). The return books a tagged open entry at the
               original unit cost, which the credit note later clears
               (Dr GDNI / Cr COGS, or Dr AP / Cr GRNI).

Sales return:     Dr Inventory   Cr GDNI (netted, reconciled)   Cr GDNI (open)
Purchase return:  Dr GRNI (netted, reconciled)   Dr GRNI (open)   Cr Inventory

Entries carry origin_type "sales_return" / "purchase_return"; clearing.delivered_qty and
clearing.received_qty use that to keep returns out of the delivered/received totals.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from accounting.models import AccountMove, AccountMoveLine, Journal
from accounting.services.Period_validators import PeriodValidator
from accounting.services.account_move_services.customer.sales_gdni_account_move import (
    _get_inventory_account,
    _get_stock_output_account,
)
from accounting.services.account_move_services.shared.account_utils import assert_same_company
from accounting.services.account_move_services.shared.invoice.clearing import (
    ClearingState,
    allocate_open_entries,
    apply_clearing,
    delivered_qty,
    invoiced_qty,
    open_total,
    received_qty,
    returned_purchase_qty,
    returned_sales_qty,
    source_ref,
)
from accounting.services.account_move_services.vendor.purchase_grni_account_move import (
    _get_stock_input_account,
)
from inventory.models import StockMove, StockPicking

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_date(value):
    return value.date() if hasattr(value, "date") else value


# ---------------------------------------------------------------------------
# The two flavours
# ---------------------------------------------------------------------------

SALES = {
    "label": "sales return",
    "link_field": "sale_line",
    "origin": "sales_return",
    "pair_origin": "delivery",        # the entry the return cancels
    "pair_kind": "gdni",
    "open_kind": "gdni_ret",
    "pair_is_debit": True,            # delivery left an open DEBIT on GDNI -> return CREDITS it
    "doc_types": ("out_invoice",),
    "pair_account": _get_stock_output_account,
    "base_qty": delivered_qty,
    "returned_qty": returned_sales_qty,
}

PURCHASE = {
    "label": "purchase return",
    "link_field": "purchase_line",
    "origin": "purchase_return",
    "pair_origin": "receiving",
    "pair_kind": "grni",
    "open_kind": "grni_ret",
    "pair_is_debit": False,           # receipt left an open CREDIT on GRNI -> return DEBITS it
    "doc_types": ("in_invoice",),
    "pair_account": _get_stock_input_account,
    "base_qty": received_qty,
    "returned_qty": returned_purchase_qty,
}


@transaction.atomic
def create_valuation_for_sales_return(picking, user):
    return _value_return(picking, user, SALES)


@transaction.atomic
def create_valuation_for_purchase_return(picking, user):
    return _value_return(picking, user, PURCHASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_pair_entries(cfg, company, link, account):
    side = {"debit__gt": 0} if cfg["pair_is_debit"] else {"credit__gt": 0}
    return list(
        AccountMoveLine.objects
        .filter(
            account=account,
            move__company=company,
            move__state=AccountMove.State.POSTED,
            move__origin_type=cfg["pair_origin"],
            reconciled=False,
            **side,
            **source_ref(link),
        )
        .select_related("move")
        .order_by("move__issue_date", "id")
        .select_for_update(of=("self",))
    )


def _original_unit_cost(cfg, company, link, account, base_qty, product):
    """Average cost the original delivery/receipt booked for this order line;
    falls back to product_cost when nothing was booked."""
    col = "debit" if cfg["pair_is_debit"] else "credit"
    total = (
        AccountMoveLine.objects
        .filter(
            account=account,
            move__company=company,
            move__state=AccountMove.State.POSTED,
            move__origin_type=cfg["pair_origin"],
            **source_ref(link),
        )
        .aggregate(s=Sum(col))["s"]
        or ZERO
    )
    if total > ZERO and base_qty > ZERO:
        return Decimal(total) / base_qty
    return Decimal(str(product.product_cost or 0))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _value_return(picking, user, cfg):
    picking = (
        StockPicking.objects.select_for_update()
        .select_related("company", "company__currency", "partner", "sales_order", "sales_order__partner")
        .get(pk=picking.pk)
    )

    if picking.account_move_id:
        return picking.account_move
    if picking.status != "COMPLETED":
        raise ValidationError(f"Only a completed picking can be valued as a {cfg['label']}.")

    company = picking.company
    if not company or not company.currency:
        raise ValidationError("The picking's company or its currency is not configured.")
    company_currency = company.currency

    raw_date = picking.date_done or picking.created_at
    if not raw_date:
        raise ValidationError(f"Picking '{picking}' has no valuation date.")
    valuation_date = _as_date(raw_date)
    PeriodValidator.validate_period(company, valuation_date)

    journal = Journal.objects.filter(company=company, type="INVENTORY").first()
    if not journal:
        raise ValidationError("No Inventory journal found for this company.")

    link_field = cfg["link_field"]
    stock_moves = list(
        StockMove.objects.filter(picking=picking, status="COMPLETED")
        .select_related("product", "product__category", "product__company", link_field)
        .prefetch_related("lines")
        .order_by("id")
    )

    # -- collect returned qty per order line ------------------------------------
    records = {}  # link pk -> {"link", "product", "qty"}
    for stock_move in stock_moves:
        product = stock_move.product
        if product.product_type != "storable" or product.get_valuation_method() != "automated":
            continue
        link = getattr(stock_move, link_field)
        if link is None:
            raise ValidationError(
                f"Returned stock move {stock_move.pk} for '{product.name}' has no "
                f"{link_field.replace('_', ' ')}; a {cfg['label']} must reference the original order line."
            )
        lines = list(stock_move.lines.all())
        if not lines:
            raise ValidationError(f"Completed stock move {stock_move.pk} has no stock move lines.")
        for line in lines:
            if line.product_id != product.pk:
                raise ValidationError(f"Stock move line {line.pk} has a different product from its stock move.")
            qty = Decimal(str(line.quantity_in_storage_uom))
            if qty <= 0:
                raise ValidationError(f"Stock move line {line.pk} has a non-positive quantity.")
            rec = records.setdefault(link.pk, {"link": link, "product": product, "qty": ZERO})
            rec["qty"] += qty

    if not records:
        raise ValidationError(f"Picking '{picking}' has no stock-tracked quantities to value.")

    # -- value each order line -----------------------------------------------------
    state = ClearingState()
    specs = []                       # lines to create
    inventory_totals = defaultdict(Decimal)
    inventory_accounts = {}
    pair_is_debit = cfg["pair_is_debit"]
    partner = picking.partner
    if partner is None and cfg is SALES:
        partner = getattr(picking.sales_order, "partner", None)

    for rec in records.values():
        link, product, r = rec["link"], rec["product"], rec["qty"]

        inventory_account = _get_inventory_account(product)
        if not inventory_account:
            raise ValidationError(f"Product '{product.name}' has no inventory account.")
        assert_same_company(inventory_account, company, "Inventory account")

        pair_account = cfg["pair_account"](product)
        if not pair_account:
            raise ValidationError(f"Product '{product.name}' has no Stock Output / Stock Input account.")
        if not pair_account.allow_reconciliation:
            raise ValidationError(f"Account '{pair_account.name}' must allow reconciliation.")
        assert_same_company(pair_account, company, "Stock interim account")

        if cfg is PURCHASE and partner is None:
            partner = getattr(getattr(link, "purchase_order", None), "partner", None)

        # Split r into netted (document not yet invoiced) and open (already invoiced)
        base_qty = cfg["base_qty"](link, exclude_picking=picking)
        doc_qty = invoiced_qty(link, cfg["doc_types"])
        pool_total = max(ZERO, base_qty - doc_qty)
        netted_prev = min(cfg["returned_qty"](link), pool_total)
        remaining = pool_total - netted_prev
        netted_now = min(r, remaining)
        open_now = r - netted_now

        netted_amount, allocs = ZERO, []
        if netted_now > ZERO:
            entries = _open_pair_entries(cfg, company, link, pair_account)
            available = open_total(entries, cfg["pair_kind"], state)
            if available <= ZERO:
                raise ValidationError(
                    f"No open {cfg['pair_origin']} entry found for '{product.name}'. The original "
                    f"{cfg['pair_origin']} must be valued before it can be returned."
                )
            target = available if netted_now >= remaining else _money(available * netted_now / remaining)
            allocs, _ = allocate_open_entries(entries, target, cfg["pair_kind"], state)
            netted_amount = sum((a["amount"] for a in allocs), ZERO)

        open_amount = ZERO
        if open_now > ZERO:
            unit = _original_unit_cost(cfg, company, link, pair_account, base_qty, product)
            open_amount = _money(open_now * unit)

        total_amount = netted_amount + open_amount
        if total_amount <= ZERO:
            continue

        inventory_totals[inventory_account.pk] += total_amount
        inventory_accounts[inventory_account.pk] = inventory_account

        if netted_amount > ZERO:
            specs.append({
                "account": pair_account, "amount": netted_amount, "debit": not pair_is_debit,
                "memo": f"{cfg['label'].capitalize()} netted against {cfg['pair_origin']}: {picking}",
                "link": link, "open": False,
                "alloc": {
                    "side": "CREDIT" if pair_is_debit else "DEBIT",
                    f"{cfg['pair_kind']}_allocations": allocs,
                },
            })
        if open_amount > ZERO:
            specs.append({
                "account": pair_account, "amount": open_amount, "debit": not pair_is_debit,
                "memo": f"{cfg['label'].capitalize()} awaiting credit note: {picking}",
                "link": link, "open": True, "alloc": None,
            })

    total = sum(inventory_totals.values(), ZERO)
    if total <= ZERO:
        raise ValidationError(f"Picking '{picking}' return valuation must be greater than zero.")

    for acc_id, amount in inventory_totals.items():
        specs.append({
            "account": inventory_accounts[acc_id], "amount": amount, "debit": pair_is_debit,
            "memo": f"Inventory {'returned' if cfg is SALES else 'sent back'}: {picking}",
            "link": None, "open": False, "alloc": None,
        })

    # -- header + lines -----------------------------------------------------------
    move = AccountMove.objects.create(
        move_type="entry",
        issue_date=valuation_date,
        company=company,
        currency=company_currency,
        currency_rate=Decimal("1.000000"),
        journal=journal,
        partner=partner,
        ref=f"{cfg['label'].capitalize()} valuation: {picking}",
        created_by=user,
        origin_type=cfg["origin"],
        origin_id=picking.pk,
    )

    objs = []
    for sp in specs:
        kw = {
            "move": move,
            "account": sp["account"],
            "partner": partner if sp["link"] is not None else None,
            "debit": sp["amount"] if sp["debit"] else ZERO,
            "credit": ZERO if sp["debit"] else sp["amount"],
            "date": valuation_date,
            "memo": sp["memo"],
            "original_amount": sp["amount"],
            "line_type": AccountMoveLine.LineType.PLAIN,
        }
        if sp["link"] is not None:
            kw.update(source_ref(sp["link"]))
        objs.append(AccountMoveLine(**kw))

    total_debit = sum((o.debit for o in objs), ZERO)
    total_credit = sum((o.credit for o in objs), ZERO)
    if total_debit != total_credit:
        raise ValidationError(f"Unbalanced return valuation: DR {total_debit} != CR {total_credit}.")

    for o in objs:
        o.full_clean()
    AccountMoveLine.objects.bulk_create(objs)

    open_residual = sum((sp["amount"] for sp in specs if sp["open"]), ZERO)
    move.amount_total = move.amount_untaxed = total_debit
    move.amount_residual = open_residual
    move.reconciled = open_residual <= ZERO
    move.save(update_fields=["amount_total", "amount_untaxed", "amount_residual", "reconciled"])
    move.post(user)

    # Netted lines are matched to the original delivery/receipt entries right away.
    for sp, obj in zip(specs, objs):
        if sp["alloc"]:
            apply_clearing(sp["alloc"], obj, cfg["pair_kind"], user)

    picking.account_move = move
    picking.save(update_fields=["account_move"])
    return move
