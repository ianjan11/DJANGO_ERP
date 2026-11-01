from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine

REFUND_MOVE_TYPES = (AccountMove.MoveType.IN_REFUND, AccountMove.MoveType.OUT_REFUND)

CREDIT_TYPE_MAP = {
    AccountMove.MoveType.OUT_INVOICE: AccountMove.MoveType.OUT_REFUND,
    AccountMove.MoveType.IN_INVOICE: AccountMove.MoveType.IN_REFUND,
}

TWO_PLACES = Decimal("0.01")


@transaction.atomic
def create_credit_from_invoice(invoice, lines_data, user, journal=None, reason="correction"):
    """
    lines_data: list of {"line": AccountMoveLine, "amount": Decimal}
    amount is the total credit for that line (subtotal basis, no tax),
    distributed equally across the line's full original quantity.

    Creates the credit note as a DRAFT with product lines only.
    """
    credit_type = CREDIT_TYPE_MAP.get(invoice.move_type)
    if credit_type is None:
        raise ValidationError("This invoice type is not supported.")

    if invoice.state != AccountMove.State.POSTED:
        raise ValidationError("Only posted invoices can be credited.")

    if not lines_data:
        raise ValidationError("No lines selected to credit.")

    credit_move = AccountMove.objects.create(
        state=AccountMove.State.DRAFT,
        created_by=user,
        partner=invoice.partner,
        currency=invoice.currency,
        company_id=invoice.company_id,
        journal=journal or invoice.journal,  # journal is required on the new model
        fulfillment_location=invoice.fulfillment_location,
        payment_term=invoice.payment_term,
        move_type=credit_type,
        reversal_of=invoice,
        reversal_reason=reason,
        origin_reference=invoice.name or "",
        currency_rate = invoice.currency_rate,
    )

    # Invoice product lines are credited on income/expense side; the credit note flips it.
    # out_refund: debit the income account. in_refund: credit the expense account.
    is_customer = credit_type == AccountMove.MoveType.OUT_REFUND

    for entry in lines_data:
        line = entry["line"]
        amount = Decimal(entry["amount"])

        if line.move_id != invoice.pk or line.line_type != AccountMoveLine.LineType.PRODUCT:
            raise ValidationError("Selected line does not belong to this invoice.")

        remaining = get_remaining_creditable_amount(line)
        if amount > remaining + TWO_PLACES:
            raise ValidationError(
                f"Cannot credit {amount} on '{line.description}' — only "
                f"{remaining} remains creditable."
            )

        per_unit_credit = (amount / line.quantity).quantize(TWO_PLACES)

        # ceiling: can't credit more per unit than the discounted price actually charged
        if per_unit_credit > line.discounted_unit_price_rounded():
            raise ValidationError(
                f"Per-unit credit ({per_unit_credit}) cannot exceed the "
                f"discounted unit price ({line.discounted_unit_price_rounded()}) "
                f"on '{line.description}'."
            )

        credit_line = AccountMoveLine.objects.create(  # .create() runs save() -> clean()
            move=credit_move,
            line_type=AccountMoveLine.LineType.PRODUCT,
            sequence=line.sequence,
            account=line.account,
            partner=invoice.partner,
            product=line.product,
            product_uom=line.product_uom or line.product.uom,
            quant=line.quant,
            description=line.description,
            quantity=line.quantity,       # always matches the original line
            price_unit=per_unit_credit,   # amount credited per unit
            discount_percent=Decimal("0"),
            date=credit_move.issue_date,
            source_line_type=ContentType.objects.get_for_model(line),
            source_line_id=line.pk,
        )
        credit_line.taxes.set(line.taxes.all())

    _recompute_totals(credit_move)
    return credit_move


def get_remaining_creditable_amount(line):
    """
    How much of this line's subtotal is still available to credit.
    `source_line` is a GenericForeignKey, so we filter on the underlying
    source_line_type / source_line_id columns directly.
    """
    prior_credit_lines = AccountMoveLine.objects.filter(
        source_line_type=ContentType.objects.get_for_model(line),
        source_line_id=line.pk,
        line_type=AccountMoveLine.LineType.PRODUCT,
        move__move_type__in=REFUND_MOVE_TYPES,
        move__state__in=(AccountMove.State.POSTED, AccountMove.State.DRAFT),
    )

    already_credited = sum(
        (cl.subtotal() for cl in prior_credit_lines),
        Decimal("0"),
    )

    return line.subtotal() - already_credited


def _recompute_totals(move):
    # tax_summary is a cached_property; drop any stale cache before reading it
    move.__dict__.pop("tax_summary", None)

    move.amount_untaxed = move.untaxed_amount
    move.amount_tax = move.total_tax
    move.amount_total = move.total_amount
    move.amount_residual = move.amount_total
    move.save(update_fields=[
        "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
    ])