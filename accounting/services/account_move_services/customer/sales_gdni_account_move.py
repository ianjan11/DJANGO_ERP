from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from accounting.models import AccountMove, AccountMoveLine, Journal
from accounting.services.Period_validators import PeriodValidator
from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company, get_company_account)
from accounting.services.account_move_services.shared.invoice.clearing import (
    delivered_qty, invoiced_qty, source_ref)
from inventory.models import StockPicking, StockMove
from inventory.services.cost_and_valuation.valuation_and_costing_service import get_cost

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_date(value):
    return value.date() if hasattr(value, "date") else value


@transaction.atomic
def create_valuation_for_picking(picking, user):
    """
    Dr Stock Output / GDNI (sales-backed)  OR  Inventory Adjustment (direct outgoing)
    Cr Inventory

    * One GDNI line PER SALE LINE, tagged with source_line, so the customer
      invoice can match and clear exactly that line's delivery cost.
    * Units that were already invoiced before they were delivered have already
      been credited to Inventory by the invoice (Dr COGS / Cr Inventory), so they
      are skipped here. Returns None if the whole picking was pre-invoiced.
    """
    picking = (
        StockPicking.objects.select_for_update()
        .select_related("company", "company__currency", "partner", "sales_order", "sales_order__partner")
        .get(pk=picking.pk)
    )

    if picking.account_move_id:
        return picking.account_move
    if picking.status != "COMPLETED":
        raise ValidationError("Only a completed picking can be valued.")

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

    partner = picking.partner or getattr(picking.sales_order, "partner", None)

    stock_moves = list(
        StockMove.objects.filter(picking=picking, status="COMPLETED")
        .select_related("product", "product__category", "product__company", "sale_line")
        .prefetch_related("lines")
        .order_by("id")
    )

    # -- pass 1: executed quantities + counterpart per move ---------------------
    pending = []  # (product, inventory_account, counterpart_account, valued_qty, sale_line)
    qty_by_product = defaultdict(Decimal)
    products = {}
    pre_invoiced = {}  # sale_line.pk -> qty invoiced ahead of delivery, still unspent
    is_sales_backed_picking = False
    skipped_any = False

    for stock_move in stock_moves:
        product = stock_move.product
        if product.product_type != "storable" or product.get_valuation_method() != "automated":
            continue

        inventory_account = _get_inventory_account(product)
        if not inventory_account:
            raise ValidationError(f"Product '{product.name}' has no inventory account.")
        assert_same_company(inventory_account, company, "Inventory account")

        sale_line = stock_move.sale_line if stock_move.sale_line_id else None
        if sale_line is not None:
            is_sales_backed_picking = True
            counterpart_account = _get_stock_output_account(product)  # GDNI (reconcilable)
            if not counterpart_account:
                raise ValidationError(f"Product '{product.name}' has no Stock Output / GDNI account.")
            if not counterpart_account.allow_reconciliation:
                raise ValidationError(f"Stock Output account '{counterpart_account.name}' must allow reconciliation.")
            assert_same_company(counterpart_account, company, "Stock Output account")
        else:
            counterpart_account = _get_inventory_adjustment_account(product)
            if not counterpart_account:
                raise ValidationError(f"Product '{product.name}' has no Inventory Adjustment / Counterpart account.")
            assert_same_company(counterpart_account, company, "Counterpart account")

        execution_lines = list(stock_move.lines.all())
        if not execution_lines:
            raise ValidationError(
                f"Completed stock move {stock_move.pk} for '{product.name}' has no stock move lines.")

        for line in execution_lines:
            if line.product_id != product.pk:
                raise ValidationError(
                    f"Stock move line {line.pk} has a different product from its stock move.")
            qty = Decimal(str(line.quantity_in_storage_uom))
            if qty <= 0:
                raise ValidationError(f"Stock move line {line.pk} has a non-positive quantity.")

            qty_by_product[product.pk] += qty      # full qty leaves stock -> cost it all
            products[product.pk] = product

            valued_qty = qty
            if sale_line is not None:
                if sale_line.pk not in pre_invoiced:
                    pre_invoiced[sale_line.pk] = max(
                        ZERO,
                        invoiced_qty(sale_line, ("out_invoice",))
                        - delivered_qty(sale_line, exclude_picking=picking),
                    )
                take = min(valued_qty, pre_invoiced[sale_line.pk])
                if take > ZERO:
                    pre_invoiced[sale_line.pk] -= take
                    valued_qty -= take
                    skipped_any = True

            if valued_qty > ZERO:
                pending.append((product, inventory_account, counterpart_account, valued_qty, sale_line))

    if not pending:
        if skipped_any:
            return None  # everything was invoiced before delivery; nothing left to post
        raise ValidationError(f"Picking '{picking}' has no stock-tracked quantities to value.")

    # -- cost once per product, for the TOTAL qty leaving in this picking --------
    cutoff = min(m.created_at for m in stock_moves)
    move_ids = [m.pk for m in stock_moves]
    unit_cost_by_product = {}
    for pid, product in products.items():
        unit_cost = get_cost(product, qty_by_product[pid], before=cutoff, exclude_move_ids=move_ids)
        if unit_cost is None:
            raise ValidationError(f"Product '{product.name}' has no unit cost.")
        unit_cost = Decimal(str(unit_cost))
        if unit_cost < 0:
            raise ValidationError(f"Product '{product.name}' has a negative unit cost.")
        unit_cost_by_product[pid] = unit_cost

    # -- pass 2: amounts ---------------------------------------------------------
    inventory_totals = defaultdict(Decimal)
    counterpart_totals = defaultdict(Decimal)   # keyed by (account pk, sale_line pk | None)
    inventory_accounts, counterpart_meta = {}, {}

    for product, inv_acc, cp_acc, qty, sale_line in pending:
        amount = _money(qty * unit_cost_by_product[product.pk])
        if amount == ZERO:
            continue
        key = (cp_acc.pk, sale_line.pk if sale_line else None)
        inventory_totals[inv_acc.pk] += amount
        counterpart_totals[key] += amount
        inventory_accounts[inv_acc.pk] = inv_acc
        counterpart_meta[key] = (cp_acc, sale_line)

    total = sum(inventory_totals.values(), ZERO)
    if total <= ZERO:
        raise ValidationError(f"Picking '{picking}' valuation must be greater than zero.")

    ref_text = f"Stock valuation: {picking}" if is_sales_backed_picking else f"Direct outgoing valuation: {picking}"

    move = AccountMove.objects.create(
        move_type="entry",
        issue_date=valuation_date,
        company=company,
        currency=company_currency,
        currency_rate=Decimal("1.000000"),
        journal=journal,
        partner=partner if is_sales_backed_picking else None,
        ref=ref_text,
        created_by=user,
        origin_type="delivery",
        origin_id=picking.pk,
    )

    lines = []
    for acc_id, amount in inventory_totals.items():  # Cr Inventory
        lines.append(AccountMoveLine(
            move=move, account=inventory_accounts[acc_id], debit=ZERO, credit=amount,
            date=valuation_date, memo=f"Inventory delivered by picking {picking}",
            original_amount=amount, line_type=AccountMoveLine.LineType.PLAIN))

    for key, amount in counterpart_totals.items():   # Dr GDNI (per sale line) / Adjustment
        cp_acc, sale_line = counterpart_meta[key]
        memo = f"GDNI for picking {picking}" if sale_line else f"Adjustment counterpart for picking {picking}"
        lines.append(AccountMoveLine(
            move=move, account=cp_acc, partner=partner if sale_line else None,
            debit=amount, credit=ZERO,
            date=valuation_date, memo=memo,
            original_amount=amount, line_type=AccountMoveLine.LineType.PLAIN,
            **(source_ref(sale_line) if sale_line else {})))

    total_debit = sum((l.debit for l in lines), ZERO)
    total_credit = sum((l.credit for l in lines), ZERO)
    if total_debit != total_credit:
        raise ValidationError(f"Unbalanced picking valuation: DR {total_debit} != CR {total_credit}.")

    for line in lines:
        line.full_clean()
    AccountMoveLine.objects.bulk_create(lines)

    move.amount_total = move.amount_untaxed = move.amount_residual = total_debit
    move.save(update_fields=["amount_total", "amount_untaxed", "amount_residual"])
    move.post(user)

    picking.account_move = move
    picking.save(update_fields=["account_move"])

    return move


def _get_inventory_account(product):
    if product.category:
        account = product.category.get_valuation_account()
        if account:
            return account
    return get_company_account(product.company, key="default_inventory_valuation_account")


def _get_stock_output_account(product):
    if product.category:
        account = product.category.get_stock_output_account()
        if account:
            return account
    return get_company_account(product.company, key="default_stock_output_account")


def _get_inventory_adjustment_account(product):
    # Direct outgoing / scrap: Dr Adjustment Expense, Cr Inventory. Must NOT be the valuation account (Dr/Cr Inventory nets to zero).
    return get_company_account(product.company, key="default_inventory_adjustment_expense")