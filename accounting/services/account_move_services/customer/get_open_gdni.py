# get_open_gdni.py
from django.core.exceptions import ValidationError

from accounting.models import AccountMove, AccountMoveLine
from accounting.services.account_move_services.customer.sales_gdni_account_move import (
    _get_stock_output_account,
)
from accounting.services.account_move_services.shared.invoice.clearing import source_ref
from sales.models import SalesOrderLine


def get_open_gdni_entries(invoice, item, for_update=False):
    """
    Open GDNI debit lines created by deliveries of THIS sales order line.
    Matching is exact (source_line on the GDNI line), not inferred from
    picking ids, and does not depend on the invoice partner matching the
    delivery partner.
    """
    order_line = item.source_line

    if not isinstance(order_line, SalesOrderLine):
        return AccountMoveLine.objects.none()

    stock_output_account = _get_stock_output_account(item.product)
    if not stock_output_account:
        raise ValidationError(
            f"Product '{item.product.name}' has no Stock Output / GDNI account."
        )

    queryset = (
        AccountMoveLine.objects
        .filter(
            account=stock_output_account,
            move__company=invoice.company,
            move__state=AccountMove.State.POSTED,
            move__origin_type="delivery",
            debit__gt=0,
            reconciled=False,
            **source_ref(order_line),
        )
        .select_related("move")
        .order_by("move__issue_date", "id")
    )

    if for_update:
        queryset = queryset.select_for_update(of=("self",))

    return queryset
