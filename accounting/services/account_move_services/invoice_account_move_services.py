from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine, PartialReconcile

from accounting.services.Period_validators import PeriodValidator
from accounting.services.account_move_services.customer.customer_context import (
    get_customer_context,
)
from accounting.services.account_move_services.customer.customer_lines import (
    build_customer_lines,
)
from accounting.services.account_move_services.shared.invoice.clearing import apply_clearing, ClearingState
from accounting.services.account_move_services.vendor.vendor_context import (
    get_vendor_context,
)
from accounting.services.account_move_services.vendor.vendor_lines import (
    build_vendor_lines,
)
from accounting.services.account_move_services.shared.account_utils import (
    round2,
    compute_due_date,
)
from accounting.services.account_move_services.shared.balance_check import (
    check_balance,
)

from accounting.services.account_move_services.shared.invoice.calculations import (
    get_totals,
    calculate_item_accounting_totals,
)
from accounting.services.account_move_services.shared.invoice.rate_service import (
    resolve_currency_rate,
)
from accounting.services.account_move_services.shared.invoice.resolve_journal import (
    resolve_journal,
)
from accounting.services.account_move_services.shared.invoice.resolve_partner_account import (
    resolve_partner_account,
)


# ================================================================
# CONSTANTS
# ================================================================

CUSTOMER_INVOICE_TYPES = {
    "out_invoice",
    "out_refund",
}

VENDOR_INVOICE_TYPES = {
    "in_invoice",
    "in_refund",
}

REFUND_TYPES = {"out_refund", "in_refund"}


# ================================================================
# BUILD INVOICE ACCOUNT MOVE
# ================================================================

@transaction.atomic
def build_invoice_account_move(invoice, user) -> AccountMove:
    """
    Populate and balance the AccountMoveLines on `invoice`, ready for
    invoice.post(user) to be called by the caller (post_invoice).

    `invoice` IS the AccountMove now -- there's no separate move to build
    and link back, so this no longer constructs one. It writes lines
    directly onto invoice.lines and returns `invoice` itself.
    """

    # ============================================================
    # 1. PREVENT DOUBLE POSTING
    # ============================================================
    # `invoice.account_move_id` doesn't exist anymore -- invoice and move
    # are the same row, so there's nothing separate to check for. The
    # equivalent guard is state: this function only makes sense to run
    # once, while the move is still a draft.



    if invoice.move_type not in CUSTOMER_INVOICE_TYPES | VENDOR_INVOICE_TYPES:
        raise ValidationError(f"Unsupported invoice type: {invoice.move_type}")

    if invoice.move_type in REFUND_TYPES:
        # Sides here are hard-coded for invoices; refunds would post backwards.
        raise ValidationError(
            "Credit notes must be built with build_account_move_credit_notes()."
        )

    if invoice.lines.exclude(line_type=AccountMoveLine.LineType.PRODUCT).exists():
        raise ValidationError(
            "Accounting lines were already generated for this invoice."
        )

    invoice_type = invoice.move_type
    partner = invoice.partner

    # ============================================================
    # 2. VALIDATE ACCOUNTING PERIOD
    # ============================================================

    PeriodValidator.validate_period(
        invoice.company,
        invoice.issue_date,
    )

    # ============================================================
    # 3. RESOLVE JOURNAL
    # ============================================================

    journal = resolve_journal(
        invoice,
        invoice_type,
    )

    # ============================================================
    # 4. RESOLVE PARTNER ACCOUNT
    # ============================================================

    partner_account = resolve_partner_account(
        invoice,
        partner,
    )

    # ============================================================
    # 5. LOAD INVOICE ITEMS
    # ============================================================
    # Filtered to product lines: at this point (still DRAFT, guarded above)
    # only product lines should exist on invoice.lines -- the tax/receivable
    # lines this function itself is about to build don't exist yet. The
    # filter makes that assumption explicit instead of relying on it
    # silently, since AccountMoveLine is polymorphic now and a re-entrant
    # or partially-run call could otherwise reprocess a GL line as if it
    # were a product line.

    items = list(
        invoice.lines
        .filter(line_type=AccountMoveLine.LineType.PRODUCT)
        .select_related(
            "product",
            "product__revenue_account",
        )
        .prefetch_related(
            "taxes",
        )
        .all()
    )

    if not items:
        raise ValidationError(
            "Cannot post an invoice with no lines."
        )

    # ============================================================
    # 6. RESOLVE CURRENCY
    # ============================================================

    (
        rate,
        is_foreign,
        foreign_currency,
        company_currency,
    ) = resolve_currency_rate(invoice)

    # ============================================================
    # 7. INITIALIZE ACCUMULATORS
    # ============================================================

    line_allocations = []
    state = ClearingState()   # one per invoice, shared by every item
    tax_totals_orig = defaultdict(Decimal)
    tax_totals_ccy = defaultdict(Decimal)

    # ============================================================
    # 8. PROCESS EVERY INVOICE ITEM
    # ============================================================

    for item in items:

        product = item.product

        # --------------------------------------------------------
        # Compute item base first
        # --------------------------------------------------------

        tax_data = item.compute_taxes()

        base_orig = round2(
            tax_data["base"]
        )

        base_ccy = (
            base_orig
            if not is_foreign
            else round2(
                base_orig * rate
            )
        )

        # --------------------------------------------------------
        # Resolve accounting context
        # --------------------------------------------------------

        if invoice_type in CUSTOMER_INVOICE_TYPES:
            context = get_customer_context(
                invoice=invoice,
                item=item,
                product=product,
                item_amount_ccy=base_ccy,
                state=state,
            )

        elif invoice_type in VENDOR_INVOICE_TYPES:
            context = get_vendor_context(
                invoice=invoice,
                item=item,
                product=product,
                item_amount_ccy=base_ccy,
                state=state,
            )

        else:
            raise ValidationError(
                f"Unsupported invoice type: {invoice_type}"
            )

        # --------------------------------------------------------
        # Calculate item accounting + tax totals
        # --------------------------------------------------------

        item_totals = calculate_item_accounting_totals(
            invoice=invoice,
            item=item,
            rate=rate,
            is_foreign=is_foreign,
            context=context,
        )


        # Collect structured allocations (preserves side, source, and stock links)
        line_allocations.extend(item_totals["allocations"])

        # --------------------------------------------------------
        # Accumulate tax totals (grouped by Tax GL Account)
        # --------------------------------------------------------

        for tax_account, amount in item_totals["tax_totals_orig"].items():
            tax_totals_orig[tax_account] += amount

        for tax_account, amount in item_totals["tax_totals_ccy"].items():
            tax_totals_ccy[tax_account] += amount

    # ============================================================
    # 9. CALCULATE INVOICE TOTALS
    # ============================================================

    (
        partner_amount_ccy,
        partner_amount_orig,
        total_tax_ccy,
        subtotal_ccy,
    ) = get_totals(
        tax_totals_orig=tax_totals_orig,
        tax_totals_ccy=tax_totals_ccy,
        line_allocations=line_allocations,
    )

    # ============================================================
    # 10. COMPUTE DUE DATE
    # ============================================================

    due_date = compute_due_date(invoice)

    if (
        not due_date
        and not getattr(invoice, "payment_term", None)
    ):
        raise ValidationError(
            "Invoice must have either a payment term or "
            "a computable due date before it can be posted."
        )

    # ============================================================
    # 11. ASSIGN MOVE NUMBER
    # ============================================================
    # NOTE: this calls journal.get_next_number(), while AccountMove.post()
    # (added when Invoice/AccountMove were unified) falls back to
    # journal.next_name() if `name` is still blank when post() runs. Same
    # job, two different method names on Journal -- harmless for invoices
    # specifically, since this line always sets `name` first and post()'s
    # fallback only fires `if not self.name`, but it's a real inconsistency
    # for plain journal entries/payments, which never go through this
    # function and so only ever hit the `next_name()` path. Worth picking
    # one name on Journal and using it everywhere; I didn't rename it here
    # since that's a change to accounting/models.py, not this file.

    if not invoice.name or invoice.name == '/':
        invoice.name = journal.get_next_number()

    # ============================================================
    # 12. UPDATE INVOICE TOTALS
    # ============================================================
    invoice.due_date = due_date
    invoice.amount_untaxed = subtotal_ccy
    invoice.amount_tax = total_tax_ccy
    invoice.amount_total = partner_amount_ccy
    invoice.amount_residual = partner_amount_ccy
    invoice.currency_rate = rate

    invoice.full_clean(
        exclude=[
            "amount_residual",
        ]
    )

    # NOTE: "updated_at" was in the original update_fields list, but
    # AccountMove (and Invoice before it) has no such field -- this would
    # have raised FieldDoesNotExist the first time this ran. Dropped it
    # here; add `updated_at = models.DateTimeField(auto_now=True)` to
    # AccountMove and put it back if you want real change-tracking.
    invoice.save(
        update_fields=[
            "name",
            "due_date",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "amount_residual",
            "currency_rate",
        ]
    )

    # ============================================================
    # 13. BUILD ACCOUNT MOVE LINES
    # ============================================================
    # `move=invoice` dropped from both calls: build_customer_lines and
    # build_vendor_lines no longer take a `move` parameter now that
    # `invoice` and the move are the same object.

    if invoice_type in CUSTOMER_INVOICE_TYPES:

        lines = build_customer_lines(
            invoice=invoice,
            invoice_type=invoice_type,
            partner=partner,

            line_allocations=line_allocations,

            tax_totals_ccy=tax_totals_ccy,
            tax_totals_orig=tax_totals_orig,

            foreign_currency=foreign_currency,

            partner_amount_orig=partner_amount_orig,
            partner_account=partner_account,
            partner_amount_ccy=partner_amount_ccy,
        )

    elif invoice_type in VENDOR_INVOICE_TYPES:

        lines = build_vendor_lines(
            invoice=invoice,
            invoice_type=invoice_type,
            partner=partner,

            line_allocations=line_allocations,

            tax_totals_ccy=tax_totals_ccy,
            tax_totals_orig=tax_totals_orig,

            foreign_currency=foreign_currency,

            partner_amount_orig=partner_amount_orig,
            partner_account=partner_account,
            partner_amount_ccy=partner_amount_ccy,
        )

    else:
        raise ValidationError(
            f"Invoice type '{invoice_type}' is not supported."
        )

    # ============================================================
    # 14. BALANCE CHECK
    # ============================================================


    check_balance(lines)

    # ============================================================
    # 15. CREATE MOVE LINES
    # ============================================================

    AccountMoveLine.objects.bulk_create(lines)


    # ============================================================
    # 15b. PERSIST GRNI / GDNI RECONCILIATION
    #      (must run after bulk_create — needs real PKs on the
    #      invoice-side lines to satisfy PartialReconcile's FKs)
    # ============================================================

    for alloc in line_allocations:
        kind = alloc.get("source")
        if kind in ("gdni", "grni") and alloc.get(f"{kind}_allocations"):
            apply_clearing(alloc, alloc["line"], kind, user)

    # ============================================================
    # 16. RETURN
    # ============================================================
    # Posting itself (state=POSTED, posted_by, posted_at) happens in
    # post_invoice, right after this returns -- unchanged from before.

    return invoice