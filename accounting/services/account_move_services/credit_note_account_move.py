from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine, Journal
from accounting.services.Period_validators import PeriodValidator
from accounting.services.account_move_services.customer.sales_gdni_account_move import (
    _get_stock_output_account,
)
from accounting.services.account_move_services.shared.account_utils import (
    get_company_account, assert_same_company, round2,
    assert_reconcilable, make_move_line, resolve_line_account)
from accounting.services.account_move_services.shared.invoice.clearing import (
    ClearingState, allocate_open_entries, apply_clearing, open_total, source_ref)
from accounting.services.account_move_services.vendor.purchase_grni_account_move import (
    _get_stock_input_account,
)
from core.services.currency_exchange_service import _get_rate
from purchases.models import PurchaseOrderLine
from sales.models import SalesOrderLine

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CREDIT_TYPE_MAP = {
    AccountMove.MoveType.IN_REFUND: {
        "journal_type": "PURCHASE",
        "partner_account": "account_payable",
        "company_default": "default_payable",
        "credit_account": "default_vendor_credit_note_account",
        "label": "payable",

        "partner_line_side": "DR",  # Reduces Payable balance
        "item_line_side": "CR",     # Reverses expense/purchase
        "tax_line_side": "CR",      # Reverses tax asset

        # Falls back to RECEIVABLE if your LineType has no PAYABLE member.
        "control_line_type": getattr(
            AccountMoveLine.LineType, "PAYABLE", AccountMoveLine.LineType.RECEIVABLE
        ),
        "display_name": "Vendor Credit Note",
    },
    AccountMove.MoveType.OUT_REFUND: {
        "journal_type": "SALE",
        "partner_account": "account_receivable",
        "company_default": "default_receivable",
        "credit_account": "default_customer_credit_note_account",
        "label": "receivable",

        "partner_line_side": "CR",  # Reduces Receivable balance
        "item_line_side": "DR",     # Reverses Revenue
        "tax_line_side": "DR",      # Reverses tax liability

        "control_line_type": AccountMoveLine.LineType.RECEIVABLE,
        "display_name": "Customer Credit Note",
    },
}

REFUND_TYPE_MAP = {
    AccountMove.MoveType.OUT_INVOICE: AccountMove.MoveType.OUT_REFUND,
    AccountMove.MoveType.IN_INVOICE: AccountMove.MoveType.IN_REFUND,
    AccountMove.MoveType.OUT_REFUND: AccountMove.MoveType.OUT_REFUND,
    AccountMove.MoveType.IN_REFUND: AccountMove.MoveType.IN_REFUND,
}


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _resolve_account(value, company, label):
    """Company settings may hold an Account instance or just its pk."""
    if value is None:
        return None
    if not hasattr(value, "pk"):
        from accounting.models import Account
        try:
            value = Account.objects.get(pk=value)
        except Account.DoesNotExist:
            raise ValidationError(f"{label} (id={value}) does not exist.")
    assert_same_company(value, company, label)
    return value


def _item_account(item, invoice, is_customer, fallback):
    """
    Account for one credit-note line, resolved the same way the invoice
    builder does: the line's own account, then the product/category account.
    The company-wide credit note account is only a last resort, so zero-rated,
    exempt and export sales keep their own revenue accounts.
    """
    if item.account_id:
        return item.account

    if item.product_id:
        product = item.product
        if is_customer:
            kind = "revenue"
        else:
            kind = "inventory" if product.product_type == "storable" else "expense"
        try:
            return resolve_line_account(item, invoice, kind)
        except ValidationError:
            pass

    if fallback is None:
        raise ValidationError(
            f"No account could be resolved for credit note line {item.pk}, and no "
            "default credit note account is configured."
        )
    return fallback


# ---------------------------------------------------------------------------
# Returned-stock reversal (customer credit note for returned goods)
# ---------------------------------------------------------------------------

def _sale_line_for(item):
    """The SalesOrderLine behind a credit-note line (directly, or via the
    original invoice line it credits)."""
    src = item.source_line
    if isinstance(src, SalesOrderLine):
        return src
    if isinstance(src, AccountMoveLine) and isinstance(src.source_line, SalesOrderLine):
        return src.source_line
    return None


def _open_return_entries(invoice, sale_line, gdni_account):
    """Open GDNI CREDIT lines posted by the return receipt of this sale line."""
    return list(
        AccountMoveLine.objects
        .filter(
            account=gdni_account,
            move__company=invoice.company,
            move__state=AccountMove.State.POSTED,
            move__origin_type="sales_return",
            credit__gt=0,
            reconciled=False,
            **source_ref(sale_line),
        )
        .select_related("move")
        .order_by("move__issue_date", "id")
        .select_for_update(of=("self",))
    )


def _build_return_stock_lines(invoice, items, partner, issue_date, ref):
    """
    The return receipt already did   Dr Inventory / Cr GDNI.
    The credit note completes it:     Dr GDNI / Cr COGS,
    clearing exactly the open GDNI the return created, so COGS and stock both
    end up reversed once. Returns (lines, clearing) where clearing is a list of
    (alloc, gdni_line) for apply_clearing() after bulk_create.
    """
    state = ClearingState()
    lines, clearing = [], []

    for item in items:
        product = item.product
        qty = _to_decimal(item.quantity_in_storage_uom or 0)
        if qty <= ZERO:
            raise ValidationError(f"Credit note line {item.pk} needs a positive quantity.")

        sale_line = _sale_line_for(item)
        if sale_line is None:
            raise ValidationError(
                f"Credit note line {item.pk} for '{product.name}' is not linked to a "
                "sales order line, so its returned stock cannot be matched."
            )

        gdni_account = _get_stock_output_account(product)
        if not gdni_account:
            raise ValidationError(f"Product '{product.name}' has no Stock Output / GDNI account.")

        entries = _open_return_entries(invoice, sale_line, gdni_account)
        available = open_total(entries, "gdni_ret", state)
        if available <= ZERO:
            raise ValidationError(
                f"No valued return receipt found for '{product.name}'. Complete the "
                "return and let it be valued before posting this credit note."
            )

        unit_cost = _to_decimal(product.product_cost or 0)
        target = min(available, round2(qty * unit_cost))
        if target <= ZERO:
            continue

        allocs, _ = allocate_open_entries(entries, target, "gdni_ret", state)
        amount = sum((a["amount"] for a in allocs), ZERO)
        if amount <= ZERO:
            continue

        cogs_account = resolve_line_account(item, invoice, "cogs")
        tag = source_ref(sale_line)

        gdni_line = make_move_line(
            move=invoice, account=gdni_account, partner=partner,
            debit=amount, credit=ZERO, date=issue_date,
            memo=f"GDNI cleared by return: {ref}",
            foreign_currency=None,           # stock legs are company-currency only
            original_amount=ZERO,
            line_type=AccountMoveLine.LineType.PLAIN,
        )
        gdni_line.source_line_type = tag["source_line_type"]
        gdni_line.source_line_id = tag["source_line_id"]

        cogs_line = make_move_line(
            move=invoice, account=cogs_account, partner=partner,
            debit=ZERO, credit=amount, date=issue_date,
            memo=f"COGS reversal: {ref}",
            foreign_currency=None,
            original_amount=ZERO,
            line_type=AccountMoveLine.LineType.PLAIN,
        )

        lines.extend([gdni_line, cogs_line])
        clearing.append(({"side": "DEBIT", "gdni_ret_allocations": allocs}, gdni_line))

    return lines, clearing


# ---------------------------------------------------------------------------
# Returned-stock clearing for VENDOR credit notes
# ---------------------------------------------------------------------------

def _purchase_line_for(item):
    src = item.source_line
    if isinstance(src, PurchaseOrderLine):
        return src
    if isinstance(src, AccountMoveLine) and isinstance(src.source_line, PurchaseOrderLine):
        return src.source_line
    return None


def _vendor_return_clear(invoice, item, base_ccy, state):
    """
    The purchase return left an open Dr GRNI (goods sent back after being billed).
    The vendor credit note clears it:  Dr AP / Cr GRNI, up to the line amount; any
    remainder (price difference) stays on the normal account.
    Returns None if nothing is open, else (grni_account, clear_ccy, allocs, purchase_line).
    """
    purchase_line = _purchase_line_for(item)
    if purchase_line is None:
        return None
    grni_account = _get_stock_input_account(item.product)
    if not grni_account:
        return None
    entries = list(
        AccountMoveLine.objects
        .filter(
            account=grni_account,
            move__company=invoice.company,
            move__state=AccountMove.State.POSTED,
            move__origin_type="purchase_return",
            debit__gt=0,
            reconciled=False,
            **source_ref(purchase_line),
        )
        .select_related("move")
        .order_by("move__issue_date", "id")
        .select_for_update(of=("self",))
    )
    available = open_total(entries, "grni_ret", state)
    target = min(available, base_ccy)
    if target <= ZERO:
        return None
    allocs, _ = allocate_open_entries(entries, target, "grni_ret", state)
    clear_ccy = sum((a["amount"] for a in allocs), ZERO)
    if clear_ccy <= ZERO:
        return None
    return grni_account, clear_ccy, allocs, purchase_line


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@transaction.atomic
def build_account_move_credit_notes(invoice: AccountMove, user) -> AccountMove:
    """
    Write the accounting lines for a draft credit note (AccountMove) onto
    `invoice.lines` and update its header. It does NOT post: post_refund_invoices
    sets the residual / payment state and calls invoice.post(user) afterwards.

    Supports 'out_refund' (Customer Credit Note) and 'in_refund' (Vendor Credit Note).
    A customer credit note with reversal_reason == 'return' also reverses the
    stock cost (Dr GDNI / Cr COGS) against the open GDNI created by the return
    return (Dr GDNI / Cr COGS). A vendor credit note with reason 'return' clears the
    open GRNI left by the purchase return (Dr AP / Cr GRNI). Applying the credit note to the original invoice is a separate,
    manual reconciliation step.
    """

    target_move_type = REFUND_TYPE_MAP.get(invoice.move_type)
    credit_type = CREDIT_TYPE_MAP.get(target_move_type)
    if not credit_type:
        raise ValidationError(
            f"Cannot build a credit note move for move_type '{invoice.move_type}'."
        )



    if invoice.lines.exclude(line_type=AccountMoveLine.LineType.PRODUCT).exists():
        raise ValidationError("Accounting lines were already generated for this credit note.")

    is_customer = target_move_type == AccountMove.MoveType.OUT_REFUND
    is_return = is_customer and invoice.reversal_reason == "return"
    is_vendor_return = (not is_customer) and invoice.reversal_reason == "return"

    # ------------------------------------------------------------------
    # 1. Derive company, currency, date, reference
    # ------------------------------------------------------------------
    company = invoice.company
    currency = invoice.currency
    issue_date = invoice.issue_date
    due_date = getattr(invoice, "due_date", None) or issue_date
    ref = invoice.origin_reference or (
        invoice.reversal_of.name if invoice.reversal_of else invoice.name
    )

    # ------------------------------------------------------------------
    # 2. Period guard
    # ------------------------------------------------------------------
    PeriodValidator.validate_period(company, issue_date)

    # ------------------------------------------------------------------
    # 3. Resolve journal (deterministic)
    # ------------------------------------------------------------------
    journal_type = credit_type["journal_type"]
    journal = (
        Journal.objects.filter(company=company, type=journal_type)
        .order_by("id")
        .first()
    )
    if not journal:
        raise ValidationError(
            f"No {journal_type} journal configured for company '{company}'."
        )

    # ------------------------------------------------------------------
    # 4. Resolve accounting partner
    # ------------------------------------------------------------------
    partner = invoice.partner
    if not partner:
        raise ValidationError(
            f"Invoice '{invoice}' has no accounting partner linked. "
            "Set one before confirming the credit note."
        )

    # ------------------------------------------------------------------
    # 5. Resolve AR / AP control account
    # ------------------------------------------------------------------
    partner_override_field = credit_type["partner_account"]
    control_account = (
        getattr(partner, partner_override_field, None)
        or get_company_account(company, key=credit_type["company_default"])
    )

    if not control_account:
        raise ValidationError(
            f"No {credit_type['label']} account configured for partner "
            f"'{partner}' or company '{company}'."
        )

    assert_same_company(control_account, company, credit_type["label"])
    assert_reconcilable(control_account, credit_type["label"])

    # ------------------------------------------------------------------
    # 6. Fetch credit note product lines
    # ------------------------------------------------------------------
    items = list(
        invoice.lines
        .filter(line_type=AccountMoveLine.LineType.PRODUCT)
        .select_related("product", "product__category", "account", "product_uom")
        .prefetch_related("taxes")
    )

    if not items:
        raise ValidationError("Cannot post a credit note with no product lines.")

    # ------------------------------------------------------------------
    # 7. Resolve exchange rate
    # ------------------------------------------------------------------
    is_foreign = (
        currency.pk != company.currency_id
        if hasattr(currency, "pk")
        else currency != company.currency
    )
    foreign_currency = currency if is_foreign else None

    if not is_foreign:
        rate = Decimal("1")
    else:
        rate = invoice.currency_rate or (
            invoice.reversal_of.currency_rate if invoice.reversal_of else None
        )
        if not rate:
            rate = _get_rate(company=company, currency=currency, date=issue_date)
        if not rate:
            raise ValidationError(
                f"No exchange rate found for {currency} on {issue_date}."
            )
        rate = _to_decimal(rate)

    # ------------------------------------------------------------------
    # 8. Aggregate revenue/expense and tax buckets (per-item accounts)
    # ------------------------------------------------------------------
    settings_map = company.get_settings_dict()
    fallback_account = _resolve_account(
        settings_map.get(credit_type["credit_account"]),
        company,
        "Credit note account",
    )

    account_totals_orig: dict = defaultdict(Decimal)
    tax_totals_orig: dict = defaultdict(Decimal)
    stock_items = []
    vendor_clears = []      # (account, clear_ccy, allocs, purchase_line, item)
    clear_state = ClearingState()

    for item in items:
        tax_data = item.compute_taxes()  # fail loudly if missing; never default to zero

        base_orig = round2(_to_decimal(tax_data["base"]))
        account = _item_account(item, invoice, is_customer, fallback_account)
        assert_same_company(account, company, "Credit note account")
        account_totals_orig[account] += base_orig

        for tax_line in tax_data.get("lines", []):
            tax = tax_line["tax"]
            t_acc = tax.account
            if not t_acc:
                raise ValidationError(f"Tax '{tax.name}' has no GL account configured.")
            assert_same_company(t_acc, company, "Tax account")

            tax_totals_orig[t_acc] += round2(_to_decimal(tax_line["amount"]))

        if is_return and item.product_id and item.product.product_type == "storable":
            stock_items.append(item)

        if is_vendor_return and item.product_id and item.product.product_type == "storable":
            res = _vendor_return_clear(invoice, item, round2(base_orig * rate), clear_state)
            if res:
                vendor_clears.append((*res, item))

    control_amount_orig = round2(
        sum(account_totals_orig.values()) + sum(tax_totals_orig.values())
    )

    # Vendor returns: the GRNI-cleared part gets its own tagged line, so take it out
    # of the line's normal (inventory) account.
    grni_lines_spec = []
    for grni_account, clear_ccy, allocs, purchase_line, item in vendor_clears:
        clear_orig = round2(clear_ccy / rate) if is_foreign else clear_ccy
        normal_acc = _item_account(item, invoice, is_customer, fallback_account)
        account_totals_orig[normal_acc] -= clear_orig
        if account_totals_orig[normal_acc] <= ZERO:
            del account_totals_orig[normal_acc]
        grni_lines_spec.append((grni_account, clear_ccy, clear_orig, allocs, purchase_line))

    account_totals_ccy = {acc: round2(amt * rate) for acc, amt in account_totals_orig.items()}
    tax_totals_ccy = {acc: round2(amt * rate) for acc, amt in tax_totals_orig.items()}

    subtotal_ccy = round2(
        sum(account_totals_ccy.values()) + sum(g[1] for g in grni_lines_spec)
    )
    total_tax_ccy = round2(sum(tax_totals_ccy.values()))

    # ------------------------------------------------------------------
    # 9. Build lines in memory
    # ------------------------------------------------------------------
    lines = []

    # 9a. Revenue / Expense lines
    item_is_debit = credit_type["item_line_side"] == "DR"
    for acc, amt_ccy in account_totals_ccy.items():
        lines.append(make_move_line(
            move=invoice,
            account=acc,
            partner=partner,
            debit=amt_ccy if item_is_debit else Decimal("0"),
            credit=Decimal("0") if item_is_debit else amt_ccy,
            date=issue_date,
            memo=ref,
            foreign_currency=foreign_currency,
            original_amount=account_totals_orig[acc],
            line_type=AccountMoveLine.LineType.PLAIN,
        ))

    # 9a-bis. GRNI cleared by a purchase return (credit side, tagged, reconciled later)
    grni_clearing = []
    for grni_account, clear_ccy, clear_orig, allocs, purchase_line in grni_lines_spec:
        gl = make_move_line(
            move=invoice, account=grni_account, partner=partner,
            debit=clear_ccy if item_is_debit else ZERO,
            credit=ZERO if item_is_debit else clear_ccy,
            date=issue_date, memo=f"GRNI cleared by return: {ref}",
            foreign_currency=foreign_currency, original_amount=clear_orig,
            line_type=AccountMoveLine.LineType.PLAIN,
        )
        tag = source_ref(purchase_line)
        gl.source_line_type = tag["source_line_type"]
        gl.source_line_id = tag["source_line_id"]
        lines.append(gl)
        grni_clearing.append(({"side": "DEBIT" if item_is_debit else "CREDIT",
                               "grni_ret_allocations": allocs}, gl))

    # 9b. Tax lines
    tax_is_debit = credit_type["tax_line_side"] == "DR"
    for t_acc, t_amt_ccy in tax_totals_ccy.items():
        lines.append(make_move_line(
            move=invoice,
            account=t_acc,
            partner=partner,
            debit=t_amt_ccy if tax_is_debit else Decimal("0"),
            credit=Decimal("0") if tax_is_debit else t_amt_ccy,
            date=issue_date,
            memo=f"Tax: {t_acc.name}",
            foreign_currency=foreign_currency,
            original_amount=tax_totals_orig[t_acc],
            line_type=AccountMoveLine.LineType.TAX,
        ))

    # 9c. Control line (AR / AP): derived from the revenue + tax lines ONLY,
    # so currency-conversion rounding is absorbed here and the stock legs
    # below (which balance on their own) never inflate the receivable.
    control_is_debit = credit_type["partner_line_side"] == "DR"
    sum_opposite_ccy = round2(
        sum((l.credit if control_is_debit else l.debit) for l in lines)
    )

    lines.append(make_move_line(
        move=invoice,
        account=control_account,
        partner=partner,
        debit=sum_opposite_ccy if control_is_debit else Decimal("0"),
        credit=Decimal("0") if control_is_debit else sum_opposite_ccy,
        date=issue_date,
        memo=ref,
        foreign_currency=foreign_currency,
        original_amount=control_amount_orig,
        line_type=credit_type["control_line_type"],
    ))

    # 9d. Returned-stock reversal (customer returns only)
    clearing = []
    if stock_items:
        stock_lines, clearing = _build_return_stock_lines(
            invoice, stock_items, partner, issue_date, ref
        )
        lines.extend(stock_lines)

    # ------------------------------------------------------------------
    # 10. Balance assertions
    # ------------------------------------------------------------------
    total_debit = round2(sum(l.debit for l in lines))
    total_credit = round2(sum(l.credit for l in lines))

    if total_debit != total_credit:
        raise ValidationError(
            f"Unbalanced journal entry: DR {total_debit} ≠ CR {total_credit}."
        )
    if sum_opposite_ccy <= 0:
        raise ValidationError("Credit note total must be greater than zero.")

    # ------------------------------------------------------------------
    # 11. Update header FROM the lines so header and ledger always agree
    # ------------------------------------------------------------------
    invoice.due_date = due_date
    invoice.journal = journal
    invoice.currency_rate = rate
    invoice.amount_untaxed = subtotal_ccy
    invoice.amount_tax = total_tax_ccy
    invoice.amount_total = sum_opposite_ccy
    invoice.amount_residual = sum_opposite_ccy

    invoice.full_clean(exclude=["amount_residual"])
    invoice.save(
        update_fields=[
            "due_date",
            "journal",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "amount_residual",
            "currency_rate",
        ]
    )

    # ------------------------------------------------------------------
    # 12. Validate and bulk create. Posting is the caller's job.
    # ------------------------------------------------------------------
    for line in lines:
        line.full_clean()

    AccountMoveLine.objects.bulk_create(lines)

    # Needs real PKs on the GDNI lines, so it runs after bulk_create.
    for alloc, gdni_line in clearing:
        apply_clearing(alloc, gdni_line, "gdni_ret", user)
    for alloc, grni_line in grni_clearing:
        apply_clearing(alloc, grni_line, "grni_ret", user)

    return invoice