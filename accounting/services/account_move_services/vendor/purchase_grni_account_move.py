from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine, Journal
from accounting.services.Period_validators import PeriodValidator
from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company, get_company_account)
from accounting.services.account_move_services.shared.invoice.clearing import source_ref
from core.services.currency_exchange_service import _get_rate
from inventory.models import StockPicking, StockMove
from inventory.services.cost_and_valuation.valuation_and_costing_service import get_receipt_unit_cost_document

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_date(value):
    return value.date() if hasattr(value, "date") else value


from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction


@transaction.atomic
def create_valuation_for_incoming_picking(picking, user):
    """
    Dr Inventory Asset
    Cr Stock Input / GRNI (if PO-backed) OR Inventory Adjustment / Opening Balance (if direct receipt)
    """
    picking = (
        StockPicking.objects.select_for_update()
        .select_related("company", "company__currency", "partner")
        .get(pk=picking.pk)
    )

    if picking.account_move_id:
        return picking.account_move
    if picking.status != "COMPLETED":
        raise ValidationError("Only a completed incoming picking can be valued.")

    company = picking.company
    if not company or not company.currency:
        raise ValidationError("The picking's company or its currency is not configured.")
    company_currency = company.currency

    raw_date = picking.date_done or picking.created_at
    if not raw_date:
        raise ValidationError(f"Incoming picking '{picking}' has no valuation date.")
    valuation_date = _as_date(raw_date)
    PeriodValidator.validate_period(company, valuation_date)

    journal = Journal.objects.filter(company=company, type="INVENTORY").first()
    if not journal:
        raise ValidationError("No Inventory journal found for this company.")

    stock_moves = (
        StockMove.objects.filter(picking=picking, status="COMPLETED")
        .select_related("product", "product__category", "purchase_line", "purchase_line__purchase_order")
        .prefetch_related("lines")
        .order_by("id")
    )

    entries = []  # (inventory_account, counterpart_account, amount_doc, currency)
    currencies = set()
    purchase_orders = {}
    is_direct_receipt = False
    po_line_for_entry = None

    for stock_move in stock_moves:
        product = stock_move.product
        if product.product_type != "storable" or product.get_valuation_method() != "automated":
            continue

        inventory_account = _get_inventory_account(product)
        if not inventory_account:
            raise ValidationError(f"Product '{product.name}' has no inventory account.")
        assert_same_company(inventory_account, company, "Inventory account")

        purchase_line = stock_move.purchase_line

        if purchase_line and purchase_line.purchase_order:
            # ==========================================
            # PATH A: PO-BACKED VENDOR RECEIPT
            # ==========================================
            purchase_order = purchase_line.purchase_order
            if purchase_order.company_id != company.pk:
                raise ValidationError(f"Purchase order for '{product.name}' belongs to a different company.")
            purchase_orders[purchase_order.pk] = purchase_order

            counterpart_account = _get_stock_input_account(product)  # GRNI (Liability)
            if not counterpart_account:
                raise ValidationError(f"Product '{product.name}' has no Stock Input / GRNI account.")
            if not counterpart_account.allow_reconciliation:
                raise ValidationError(f"Stock Input account '{counterpart_account.name}' must allow reconciliation.")
            assert_same_company(counterpart_account, company, "Stock Input account")

            unit_cost, currency = get_receipt_unit_cost_document(stock_move)
            unit_cost = Decimal(str(unit_cost))
            if unit_cost < 0:
                raise ValidationError(f"Purchase cost for '{product.name}' cannot be negative.")
            currencies.add(currency or company_currency)
            po_line_for_entry = purchase_line
        else:
            # ==========================================
            # PATH B: DIRECT RECEIPT / OPENING STOCK (NO PO)
            # ==========================================
            is_direct_receipt = True
            po_line_for_entry = None
            unit_cost = Decimal(str(product.product_cost))
            if unit_cost < 0:
                raise ValidationError(f"Product cost for '{product.name}' cannot be negative.")
            currency = company_currency
            currencies.add(company_currency)

            # Route to an Inventory Adjustment or Opening Balance account instead of GRNI
            counterpart_account = _get_inventory_adjustment_account(product)
            if not counterpart_account:
                raise ValidationError(f"Product '{product.name}' has no Inventory Adjustment / Counterpart account.")
            assert_same_company(counterpart_account, company, "Counterpart account")

        execution_lines = list(stock_move.lines.all())
        if not execution_lines:
            raise ValidationError(f"Completed stock move {stock_move.pk} for '{product.name}' has no execution lines.")

        for line in execution_lines:
            if line.product_id != product.pk:
                raise ValidationError(f"Stock move line {line.pk} has a product different from its stock move.")
            qty = Decimal(str(line.quantity_in_storage_uom))
            if qty <= 0:
                raise ValidationError(f"Stock move line {line.pk} has a non-positive quantity.")
            amount_doc = _money(unit_cost * qty)
            if amount_doc == ZERO:
                continue
            entries.append((inventory_account, counterpart_account, amount_doc, currency, po_line_for_entry))

    if not entries:
        raise ValidationError(f"Incoming picking '{picking}' has no stock-tracked quantities to value.")

    non_company_currencies = {c for c in currencies if c != company_currency}
    if len(non_company_currencies) > 1:
        raise ValidationError("Receipt mixes multiple purchase currencies. Split the receipt before valuation.")

    purchase_currency = non_company_currencies.pop() if non_company_currencies else company_currency
    is_foreign = purchase_currency != company_currency
    foreign_currency = purchase_currency if is_foreign else None

    # -- Exchange rate -------------------------------------------------------
    if is_foreign:
        rate = _get_rate(company=company, currency=purchase_currency, date=valuation_date)
        if not rate or Decimal(str(rate)) <= 0:
            raise ValidationError(f"No valid exchange rate found for {purchase_currency} on {valuation_date}.")
        rate = Decimal(str(rate))
    else:
        rate = Decimal("1.000000")

    # -- Convert entries -----------------------------------------------------
    inv = defaultdict(lambda: [ZERO, ZERO])
    counterpart = defaultdict(lambda: [ZERO, ZERO])   # keyed by (account pk, PO line pk | None)
    inv_acc, cp_meta = {}, {}
    for i_acc, c_acc, doc, cur, po_line in entries:
        effective_rate = rate if cur != company_currency else Decimal("1.000000")
        comp = _money(doc * effective_rate)
        key = (c_acc.pk, po_line.pk if po_line else None)
        inv[i_acc.pk][0] += doc
        inv[i_acc.pk][1] += comp
        counterpart[key][0] += doc
        counterpart[key][1] += comp
        inv_acc[i_acc.pk] = i_acc
        cp_meta[key] = (c_acc, po_line)

    total_debit = sum((v[1] for v in inv.values()), ZERO)
    total_credit = sum((v[1] for v in counterpart.values()), ZERO)
    if total_debit != total_credit:
        raise ValidationError(f"Unbalanced incoming valuation: DR {total_debit} != CR {total_credit}.")
    if total_debit <= ZERO:
        raise ValidationError("Incoming picking valuation must be greater than zero.")

    # Partner is optional for direct receipts (no vendor attached)
    partner = picking.partner or (next(iter(purchase_orders.values())).partner if purchase_orders else None)

    ref_text = f"Direct receipt valuation: {picking}" if is_direct_receipt else f"Stock receipt valuation: {picking}"

    move = AccountMove.objects.create(
        move_type="entry",
        issue_date=valuation_date,
        company=company,
        currency=company_currency,
        currency_rate=rate if is_foreign else Decimal("1.000000"),
        journal=journal,
        partner=partner,
        ref=ref_text,
        created_by=user,
        origin_type="receiving",
        origin_id=picking.pk,
    )

    lines = []
    for acc_id, (doc, comp) in inv.items():
        lines.append(AccountMoveLine(
            move=move, account=inv_acc[acc_id], debit=comp, credit=ZERO, date=valuation_date,
            memo=f"Goods received: {picking}", foreign_currency=foreign_currency if is_foreign else None,
            original_amount=doc, line_type=AccountMoveLine.LineType.PLAIN))

    memo_text = f"Opening / adjustment counterpart for: {picking}" if is_direct_receipt else f"GRNI for receipt: {picking}"
    for key, (doc, comp) in counterpart.items():   # Cr GRNI (one line per PO line)
        c_acc, po_line = cp_meta[key]
        lines.append(AccountMoveLine(
            move=move, account=c_acc, partner=partner, debit=ZERO, credit=comp,
            date=valuation_date,
            memo=memo_text,
            foreign_currency=foreign_currency if is_foreign else None,
            original_amount=doc, line_type=AccountMoveLine.LineType.PLAIN,
            **(source_ref(po_line) if po_line else {})))

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


def _get_inventory_adjustment_account(product):
    # Direct receipt / opening stock: Dr Inventory, Cr Adjustment Gain. Must NOT be the valuation account (Dr/Cr Inventory nets to zero).
    return get_company_account(product.company, key="default_inventory_adjustment_gain")



def _get_stock_input_account(product):
    if product.category:
        account = product.category.get_stock_input_account()
        if account:
            return account
    return get_company_account(product.company, key="default_stock_input_account")