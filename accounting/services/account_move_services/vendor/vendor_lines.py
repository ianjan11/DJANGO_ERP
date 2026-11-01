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


def build_vendor_lines(
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
    Build vendor invoice move lines from structured line allocations and
    attach them to `invoice.lines` -- `invoice` IS the AccountMove now, so
    the old `move` parameter is gone, same as build_customer_lines. Whatever
    calls this (build_invoice_account_move, presumably) needs to drop its
    own `move=` argument too.

    Business accounts:
        Expense / Inventory / GRNI

    Tax & Partner accounts:
        Input VAT, Accounts Payable (handled via helper)
    """

    lines = []

    # ============================================================
    # 1. RESOLVE CONFIGURATION & DEFAULT SIDE
    # ============================================================

    config = get_config(invoice_type)
    default_side = config["line_side"]  # "DEBIT" for vendor bill, "CREDIT" for vendor refund

    if default_side not in ("DEBIT", "CREDIT"):
        raise ValidationError(
            f"Invalid line side '{default_side}' "
            f"for invoice type '{invoice_type}'."
        )

    # ============================================================
    # 2. BUSINESS ACCOUNT LINES (FROM LINE ALLOCATIONS)
    # ============================================================
    # Aggregated GL legs (Expense/Inventory/GRNI), one row per account in
    # line_allocations, not one per product -- see the same note in
    # build_customer_lines about make_move_line and LineType.PLAIN.

    for alloc in line_allocations:

        account = alloc["account"]
        amount_ccy = Decimal(str(alloc["amount_ccy"]))
        amount_orig = Decimal(str(alloc["amount_orig"]))

        if amount_ccy <= Decimal("0.00"):
            continue

        # Respect explicitly assigned side on allocation if available,
        # otherwise fallback to standard default side for the invoice type.
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
            foreign_currency=foreign_currency,
            original_amount=amount_orig,
            line_type=AccountMoveLine.LineType.PLAIN

        )

        alloc["line"] = line
        lines.append(line)

    # ============================================================
    # 3. TAX LINES + PAYABLE LINE
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