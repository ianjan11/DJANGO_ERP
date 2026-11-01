# get_open_grni.py
from django.core.exceptions import ValidationError

from accounting.models import AccountMove, AccountMoveLine
from accounting.services.account_move_services.shared.invoice.clearing import source_ref
from accounting.services.account_move_services.vendor.purchase_grni_account_move import (
    _get_stock_input_account,
)
from purchases.models import PurchaseOrderLine


def get_open_grni_entries(invoice, item, for_update=False):
    """
    Open GRNI credit lines created by receipts of THIS purchase order line.
    """
    order_line = item.source_line

    if order_line is None:
        return AccountMoveLine.objects.none()

    if not isinstance(order_line, PurchaseOrderLine):
        raise ValidationError("Invoice item origin is not a purchase order line.")

    stock_input_account = _get_stock_input_account(item.product)
    if not stock_input_account:
        raise ValidationError(
            f"Product '{item.product.name}' has no Stock Input / GRNI account."
        )

    queryset = (
        AccountMoveLine.objects
        .filter(
            account=stock_input_account,
            move__company=invoice.company,
            move__state=AccountMove.State.POSTED,
            move__origin_type="receiving",
            credit__gt=0,
            reconciled=False,
            **source_ref(order_line),
        )
        .select_related("move")
        .order_by("move__issue_date", "id")
    )

    if for_update:
        queryset = queryset.select_for_update(of=("self",))

    return queryset
