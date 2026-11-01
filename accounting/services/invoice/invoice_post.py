from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from accounting.models import Account, AccountMove, AccountMoveLine
from accounting.services.credit_note_service.create_credit_note_from_invoice import get_remaining_creditable_amount




@transaction.atomic
def post_invoice(invoice, user):
    """`invoice` is an AccountMove (move_type='out_invoice'/'in_invoice'/...).
    There's no separate Invoice object to build a GL move *from* anymore --
    the accounting lines this used to construct on a fresh AccountMove now
    have to be added directly onto `invoice.lines`, alongside the product
    lines already there, before `invoice.post(user)` can balance and post it."""

    # ------------------------------------------------------------
    # 1. Lock invoice lines FIRST, before doing any expensive or
    #    side-effecting work. Fail fast and cheaply.
    # ------------------------------------------------------------

    items = list(
        invoice.lines
        .select_for_update()
        .select_related('product', 'quant')
    )

    if not items:
        raise ValidationError("Invoice has no items.")


    # ------------------------------------------------------------
    # 2. Assign the invoice number BEFORE building the GL lines.
    #    (AccountMove.post() would also assign one via the journal's
    #    own sequence if `name` were still blank when it runs -- setting
    #    it explicitly here first, as before, just means that fallback
    #    never fires; whichever sets `name` first wins, and this does.)
    # ------------------------------------------------------------

    if not invoice.name:
        from accounting.services.invoice.creator import generate_invoice_number

        invoice.name = generate_invoice_number(company=invoice.company)

    # ------------------------------------------------------------
    # 3. Populate the GL lines (tax / receivable / rounding) onto
    #    THIS move, alongside the product lines already on it, then
    #    post it. There is no separate AccountMove to build and link
    #    back anymore -- `invoice` IS the move.
    #
    #    build_invoice_account_move's contract needs updating on the
    #    service side to match: it should now write AccountMoveLine
    #    rows (line_type=TAX / RECEIVABLE / ROUNDING) onto
    #    invoice.lines directly, rather than constructing and
    #    returning a separate AccountMove. Its return value isn't
    #    used here for that reason -- `invoice` is posted directly.
    # ------------------------------------------------------------

    from accounting.services.account_move_services.invoice_account_move_services import (
        build_invoice_account_move,
    )

    build_invoice_account_move(invoice, user=user)

    invoice.post(user)   # balances, sets state=POSTED, posted_by, posted_at

    # ------------------------------------------------------------
    # 4. Totals: nothing to copy anymore -- amount_total etc. live
    #    directly on `invoice`, there's no separate move to read them
    #    off of.
    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # 5. Mark source order lines as invoiced. Runs for EVERY
    #    posted invoice type -- this must not live inside the
    #    stock-moving branch below, since qty_invoiced tracking
    #    applies to vendor bills and service-only invoices too,
    #    not just stock-moving sales invoices.
    # ------------------------------------------------------------
    mark_qty_invoiced(invoice=invoice)

    return invoice


@transaction.atomic
def mark_qty_invoiced(invoice):
    """
    Increment qty_invoiced on each source order line for every product
    line on this invoice. Called at posting time, for every invoice type.
    """
    for line in invoice.lines.filter(line_type=AccountMoveLine.LineType.PRODUCT).select_related('source_line_type'):
        order_line = line.source_line

        if order_line is None:
            continue  # manually-added line with no source order line

        new_qty_invoiced = order_line.qty_invoiced + line.quantity

        if new_qty_invoiced > order_line.invoice_target_quantity:
            raise ValidationError(
                f"Cannot post: line {order_line.id} would have "
                f"qty_invoiced={new_qty_invoiced}, exceeding its "
                f"invoiceable target of {order_line.invoice_target_quantity}."
            )

        order_line.qty_invoiced = new_qty_invoiced
        order_line.save(update_fields=['qty_invoiced'])


@transaction.atomic
def post_refund_invoices(invoice, user):
    """`invoice` is an AccountMove (move_type='out_refund'/'in_refund')."""

    items = list(
        invoice.lines
        .select_for_update()
    )

    if not items:
        raise ValidationError("Invoice has no items.")

    # Stock reversal is handled by the return flow upstream of this
    # function -- nothing to do here on that front.

    # ------------------------------------------------------------
    # 1b. Guard against crediting more than remains creditable,
    #     per line -- NOT against the invoice's grand total.
    # ------------------------------------------------------------

    for item in items:
        remaining = get_remaining_creditable_amount(item)
        amount = item.get_subtotal()

        if amount > remaining + Decimal("0.01"):
            raise ValidationError(
                f"Cannot credit {amount} on '{item.description}' -- only "
                f"{remaining} remains creditable."
            )

    # ------------------------------------------------------------
    # 2. Assign the invoice number BEFORE building the GL lines.
    # ------------------------------------------------------------

    if not invoice.name:
        from accounting.services.invoice.creator import generate_invoice_number
        invoice.name = generate_invoice_number(company=invoice.company)

    # ------------------------------------------------------------
    # 3. Populate the GL lines on THIS move and post it. As in
    #    post_invoice above, there's no separate AccountMove to build
    #    and link back anymore -- build_account_move_credit_notes'
    #    contract needs to move to writing lines directly onto
    #    invoice.lines rather than returning a standalone move.
    # ------------------------------------------------------------

    from accounting.services.account_move_services.credit_note_account_move import (
        build_account_move_credit_notes
    )

    build_account_move_credit_notes(invoice, user=user)

    # ------------------------------------------------------------
    # 4. A freshly posted credit note starts fully outstanding and
    #    unpaid -- set that before posting (post() only touches
    #    state/posted_by/posted_at/name, not payment_state/amount_residual).
    #
    #    The original here re-read amount_untaxed/amount_tax/amount_total/
    #    exchange_rate off a separate `account_move` object and copied them
    #    onto `invoice` -- with `invoice` and the move now the same object,
    #    those were self-assignments and are dropped; only amount_residual
    #    (real logic: nothing's been paid yet) and currency_rate (default
    #    to 1 if never set) are kept.
    # ------------------------------------------------------------

    invoice.amount_residual = invoice.amount_total
    invoice.payment_state = AccountMove.PaymentState.NOT_PAID
    invoice.save(update_fields=['amount_residual', 'currency_rate', 'payment_state'])

    invoice.post(user)   # sets state=POSTED, posted_by, posted_at (name already assigned above)

    return invoice