from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError

from accounting.services.account_move_services.shared.account_utils import (
    assert_same_company,
    round2,
)


# ================================================================
# TAX DATA
# ================================================================

from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError


def calculate_item_accounting_totals(
        invoice,
        item,
        rate,
        is_foreign,
        context,
):
    """
    Calculate base accounting allocations and tax totals for one invoice item.

    Supports both single-leg items (Services, Vendor Bills) and multi-leg items
    (Customer Sales with Revenue + COGS/GDNI).
    """

    allocations_output = []

    tax_totals_orig = defaultdict(Decimal)
    tax_totals_ccy = defaultdict(Decimal)

    # ============================================================
    # 1. ITEM TAX CALCULATION
    # ============================================================

    tax_data = item.compute_taxes()

    base_orig = round2(tax_data["base"])
    base_ccy = (
        base_orig if not is_foreign else round2(base_orig * rate)
    )

    # ============================================================
    # 2. ACCOUNT ALLOCATIONS
    # ============================================================

    allocations = context.get("allocations")

    if not allocations:
        raise ValidationError(
            f"No accounting allocations were resolved for invoice item {item.pk}."
        )

    primary_allocated_ccy = Decimal("0.00")

    for allocation in allocations:
        account = allocation.get("account")
        source = allocation.get("source")
        side = allocation.get("side", "DEBIT")

        amount_ccy = round2(Decimal(str(allocation.get("amount", Decimal("0.00")))))

        if is_foreign and rate:
            amount_orig = round2(amount_ccy / rate)
        else:
            amount_orig = amount_ccy

        if not account:
            raise ValidationError(
                f"Accounting allocation for invoice item {item.pk} has no account."
            )

        if amount_ccy < Decimal("0.00"):
            raise ValidationError(
                f"Accounting allocation for invoice item {item.pk} cannot be negative."
            )

        if amount_ccy == Decimal("0.00"):
            continue

        # ============================================================
        # PRIMARY VS SECONDARY ALLOCATION TRACKING
        # ============================================================
        # Only accumulate Primary Base allocations (Revenue for Sales, Expense/GRNI for Bills).
        # Secondary inventory valuation movements (e.g., COGS / GDNI legs) must be excluded
        # from the tax base validation check.
        is_primary = allocation.get("is_primary", source in ("revenue", "expense"))

        if is_primary:
            primary_allocated_ccy += amount_ccy

        allocations_output.append(
            {
                "account": account,
                "amount_ccy": amount_ccy,
                "amount_orig": amount_orig,
                "side": side,
                "source": source,
                "is_primary": is_primary,
                "gdni_allocations": allocation.get("gdni_allocations", []),
                "grni_allocations": allocation.get("grni_allocations", []),
            }
        )

    # ============================================================
    # 3. VALIDATE ALLOCATION (Primary Base vs Tax Base)
    # ============================================================

    if round2(primary_allocated_ccy) != round2(base_ccy):
        raise ValidationError(
            f"Accounting allocation mismatch for invoice item {item.pk}: "
            f"base={base_ccy}, primary_allocated={primary_allocated_ccy}."
        )

    # ============================================================
    # 4. TAX ACCOUNTS
    # ============================================================

    for tax_line in tax_data["lines"]:
        tax = tax_line["tax"]
        tax_account = tax.account

        if not tax_account:
            raise ValidationError(
                f"Tax '{tax.name}' has no GL account configured."
            )

        assert_same_company(
            tax_account,
            invoice.company,
            "Tax account",
        )

        tax_orig = round2(tax_line["amount"])
        tax_ccy = (
            tax_orig if not is_foreign else round2(tax_orig * rate)
        )

        tax_totals_orig[tax_account] += tax_orig
        tax_totals_ccy[tax_account] += tax_ccy

    # ============================================================
    # 5. RETURN STRUCTURED DICTIONARY PAYLOAD
    # ============================================================

    return {
        "item_id": item.pk,
        "base_orig": base_orig,
        "base_ccy": base_ccy,
        "allocations": allocations_output,
        "tax_totals_orig": tax_totals_orig,
        "tax_totals_ccy": tax_totals_ccy,
    }
# ================================================================
# TOTALS
# ================================================================
from decimal import Decimal


def get_totals(
    tax_totals_orig,
    tax_totals_ccy,
    line_allocations,
):
    """
    Calculate invoice header totals from accumulated tax totals and line allocations.

    Filters allocations strictly by primary sources and `is_primary=True` flags
    to prevent secondary inventory/cost legs ("cogs", "gdni", "inventory_clearing")
    from inflating subtotals.
    """

    PRIMARY_SOURCES = ("revenue", "expense", "grni", "inventory")

    # Helper function to ensure consistent filtering rules across currencies
    def is_primary_allocation(alloc):
        return (
            alloc.get("is_primary", True)
            and alloc.get("source") in PRIMARY_SOURCES
        )

    # ------------------------------------------------------------
    # 1. Untaxed Subtotal (Primary Base Legs Only)
    # ------------------------------------------------------------

    subtotal_ccy = round2(
        sum(
            (
                alloc["amount_ccy"]
                for alloc in line_allocations
                if is_primary_allocation(alloc)
            ),
            Decimal("0.00"),
        )
    )

    subtotal_orig = round2(
        sum(
            (
                alloc["amount_orig"]
                for alloc in line_allocations
                if is_primary_allocation(alloc)
            ),
            Decimal("0.00"),
        )
    )

    # ------------------------------------------------------------
    # 2. Tax Total
    # ------------------------------------------------------------

    total_tax_ccy = round2(
        sum(tax_totals_ccy.values(), Decimal("0.00"))
    )

    total_tax_orig = round2(
        sum(tax_totals_orig.values(), Decimal("0.00"))
    )

    # ------------------------------------------------------------
    # 3. Partner Receivable / Payable Amount (AR / AP Total)
    # ------------------------------------------------------------

    partner_amount_ccy = round2(subtotal_ccy + total_tax_ccy)
    partner_amount_orig = round2(subtotal_orig + total_tax_orig)

    return (
        partner_amount_ccy,
        partner_amount_orig,
        total_tax_ccy,
        subtotal_ccy,
    )