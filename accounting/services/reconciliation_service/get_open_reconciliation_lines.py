from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounting.models import AccountMoveLine, PartialReconcile

AMOUNT_FIELD = DecimalField(max_digits=15, decimal_places=2)


def _remaining_balance_queryset(qs):
    """
    Annotate each line with its actual remaining (unmatched) amount,
    computed from PartialReconcile rather than trusted off the
    `reconciled` boolean, which may not be reliably flipped on
    partial matches.

    Two separate correlated subqueries are used (rather than two
    Sum()s on matched_debit_ids / matched_credit_ids in a single
    .annotate() call) to avoid the classic Django multi-join fan-out
    bug, where aggregating across two different reverse relations in
    one annotate() silently inflates the totals.

    Only lines with a strictly positive remaining balance are kept:
    this is what makes PartialReconcile (not the `reconciled` flag)
    the source of truth for "is this line actually still open".
    """
    matched_debit_sq = (
        PartialReconcile.objects
        .filter(debit_line=OuterRef("pk"))
        .values("debit_line")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    matched_credit_sq = (
        PartialReconcile.objects
        .filter(credit_line=OuterRef("pk"))
        .values("credit_line")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    line_amount = Case(
        When(debit__gt=0, then=F("debit")),
        default=F("credit"),
        output_field=AMOUNT_FIELD,
    )

    return qs.annotate(
        line_amount=line_amount,
        matched_debit=Coalesce(
            Subquery(matched_debit_sq, output_field=AMOUNT_FIELD),
            Decimal("0"),
        ),
        matched_credit=Coalesce(
            Subquery(matched_credit_sq, output_field=AMOUNT_FIELD),
            Decimal("0"),
        ),
    ).annotate(
        remaining=ExpressionWrapper(
            F("line_amount") - F("matched_debit") - F("matched_credit"),
            output_field=AMOUNT_FIELD,
        )
    ).filter(remaining__gt=0)


def get_open_reconciliation_lines(
    company,
    start_date=None,
    end_date=None,
    search_line=None,
):
    """
    Return open reconciliation lines for the company, grouped by
    account and then by partner.

    Only posted lines belonging to reconciliation-enabled accounts
    are considered.

    Openness is determined from PartialReconcile-derived remaining
    balances, not the `reconciled` boolean.

    `start_date` and `end_date` are inclusive.
    """

    filters = {
        "move__company": company,
        "account__allow_reconciliation": True,
        "move__state": "posted",
    }

    if start_date:
        filters["date__gte"] = start_date

    if end_date:
        filters["date__lte"] = end_date

    qs = (
        AccountMoveLine.objects
        .filter(**filters)
        .select_related("account", "partner", "move")
    )

    if search_line:
        qs = qs.filter(
            Q(account__name__icontains=search_line)
            | Q(account__code__icontains=search_line)
            | Q(partner__name__icontains=search_line)
            | Q(move__ref__icontains=search_line)
            | Q(move__name__icontains=search_line)
        )

    qs = (
        _remaining_balance_queryset(qs)
        .order_by(
            "account_id",
            "partner_id",
            "date",
            "id",
        )
    )

    reconciliation_lines = {}

    for line in qs:
        account_data = reconciliation_lines.setdefault(
            line.account_id,
            {
                "name": line.account.name,
                "partners": {},
            },
        )

        partner_data = account_data["partners"].setdefault(
            line.partner_id,
            {
                "name": line.partner.name if line.partner else None,
                "lines": [],
            },
        )

        partner_data["lines"].append(line)

    return reconciliation_lines