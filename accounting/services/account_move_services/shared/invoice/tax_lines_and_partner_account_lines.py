from django.db import transaction
from decimal import Decimal

from accounting.models import AccountMoveLine
from accounting.services.account_move_services.shared.account_utils import (make_move_line)


def build_tax_lines_and_partner_account_lines(
    invoice,
    partner,
    tax_totals_ccy,
    tax_totals_orig,
    line_side,
    foreign_currency,
    move,
    partner_amount_ccy,
    partner_amount_orig,
    partner_account,
):
    """
    Build tax account lines and the partner receivable/payable line.

    Note:
        line_side refers to the side of the primary base lines:
        - "DEBIT" base lines (Vendor Bills) -> Tax is DEBIT, Partner is CREDIT.
        - "CREDIT" base lines (Customer Invoices) -> Tax is CREDIT, Partner is DEBIT.
    """
    lines = []

    # ============================================================
    # 1. TAX ACCOUNT LINES
    # ============================================================

    for tax_account, tax_amount_ccy in tax_totals_ccy.items():

        tax_amount_ccy = Decimal(str(tax_amount_ccy))

        if tax_amount_ccy <= Decimal("0.00"):
            continue

        tax_amount_orig = Decimal(
            str(tax_totals_orig.get(tax_account, Decimal("0.00")))
        )

        memo = f"Tax: {tax_account.name}"

        if line_side == "DEBIT":
            debit = tax_amount_ccy
            credit = Decimal("0.00")
        else:
            debit = Decimal("0.00")
            credit = tax_amount_ccy

        lines.append(
            make_move_line(
                move=move,
                account=tax_account,
                partner=partner,
                debit=debit,
                credit=credit,
                date=invoice.issue_date,
                memo=memo,
                foreign_currency=foreign_currency,
                original_amount=tax_amount_orig,
                line_type=AccountMoveLine.LineType.TAX

            )
        )

    # ============================================================
    # 2. PARTNER RECEIVABLE / PAYABLE LINE
    # ============================================================

    if line_side == "CREDIT":
        # Customer Invoice: Sales are CREDIT, Partner (AR) is DEBIT
        partner_debit = partner_amount_ccy
        partner_credit = Decimal("0.00")
    else:
        # Vendor Bill: Expenses/Inventory are DEBIT, Partner (AP) is CREDIT
        partner_debit = Decimal("0.00")
        partner_credit = partner_amount_ccy

    lines.append(
        make_move_line(
            move=move,
            account=partner_account,
            partner=partner,
            debit=partner_debit,
            credit=partner_credit,
            date=invoice.issue_date,
            memo=invoice.name,
            foreign_currency=foreign_currency,
            original_amount=partner_amount_orig,
            line_type = AccountMoveLine.LineType.RECEIVABLE

        )
    )

    return lines