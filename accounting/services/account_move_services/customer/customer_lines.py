from decimal import Decimal

from django.core.exceptions import ValidationError

from accounting.models import AccountMoveLine
from accounting.services.account_move_services.shared.account_utils import (
    make_move_line,
)
from accounting.services.account_move_services.shared.invoice.source_config import (
    get_config,
)
from accounting.services.account_move_services.shared.invoice.tax_lines_and_partner_account_lines import (
    build_tax_lines_and_partner_account_lines,
)


# ================================================================
# BUILD CUSTOMER ACCOUNT MOVE LINES
# ================================================================

def build_customer_lines(
    invoice,
    invoice_type,
    partner,
    line_allocations,
    tax_totals_ccy,
    tax_totals_orig,
    foreign_currency,
    partner_amount_orig,
    partner_account,
    partner_amount_ccy,
):
    """
    Build all AccountMoveLine objects for a customer invoice and attach them
    to `invoice.lines` -- `invoice` IS the AccountMove now, there's no
    separate move to build and hand back, so the old `move` parameter is
    gone. If this is still being called with a `move=` keyword from
    build_invoice_account_move, that caller needs updating to drop it and
    pass `invoice` for both.

    Handles both primary Revenue lines and secondary GDNI/COGS inventory legs
    directly from structured line allocations.

    Structure:
        1. Revenue / Cost / Inventory GL accounts (from line allocations)
        2. Output VAT / Tax accounts
        3. Accounts Receivable (Partner account)
    """

    lines = []

    # ============================================================
    # 1. RESOLVE CONFIGURATION & DEFAULT SIDE
    # ============================================================

    config = get_config(invoice_type)
    default_side = config["line_side"]  # "CREDIT" for out_invoice, "DEBIT" for out_refund

    if default_side not in ("DEBIT", "CREDIT"):
        raise ValidationError(
            f"Invalid line side '{default_side}' "
            f"for invoice type '{invoice_type}'."
        )

    # ============================================================
    # 2. BUSINESS ACCOUNT LINES (REVENUE + GDNI/COGS LEGS)
    # ============================================================
    # These are aggregated GL legs, not per-product invoice lines -- one row
    # per account in `line_allocations`, not one per product. They carry no
    # product/quantity, so they belong at AccountMoveLine.LineType.PLAIN (the
    # default) unless make_move_line sets something else; confirm that on
    # make_move_line's side since it isn't shown here.

    for alloc in line_allocations:

        account = alloc["account"]
        amount_ccy = Decimal(str(alloc["amount_ccy"]))
        amount_orig = Decimal(str(alloc["amount_orig"]))

        if amount_ccy <= Decimal("0.00"):
            continue

        # Use explicit side on allocation if specified (critical for COGS/GDNI side switches),
        # falling back to default side for simple sales lines.
        side = alloc.get("side", default_side)

        if side == "DEBIT":
            debit = amount_ccy
            credit = Decimal("0.00")
        else:
            debit = Decimal("0.00")
            credit = amount_ccy

        line = make_move_line(
            move=invoice,
            account=account,
            partner=partner,
            debit=debit,
            credit=credit,
            date=invoice.issue_date,
            memo=invoice.name,
            # COGS / GDNI / inventory legs are company-currency only; stamping
            # them with the invoice's foreign currency creates fake FX amounts.
            foreign_currency=foreign_currency if alloc.get("is_primary", True) else None,
            original_amount=amount_orig if alloc.get("is_primary", True) else Decimal("0.00"),
            line_type=AccountMoveLine.LineType.PLAIN
        )
        alloc["line"] = line
        lines.append(line)

    # ============================================================
    # 3. TAX LINES + RECEIVABLE LINE
    # ============================================================

    lines.extend(
        build_tax_lines_and_partner_account_lines(
            invoice=invoice,
            partner=partner,
            tax_totals_ccy=tax_totals_ccy,
            tax_totals_orig=tax_totals_orig,
            line_side=default_side,
            foreign_currency=foreign_currency,
            move=invoice,
            partner_amount_ccy=partner_amount_ccy,
            partner_amount_orig=partner_amount_orig,
            partner_account=partner_account,
        )
    )

    return lines