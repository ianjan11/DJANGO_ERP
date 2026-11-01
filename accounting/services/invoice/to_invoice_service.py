from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine, Journal
from inventory.models import StockPicking
from purchases.models import PurchaseOrder
from sales.models import SalesOrder

MT = AccountMove.MoveType

ORIGIN_TYPE_MAP = {
    "sales_order":     {"model": SalesOrder,     "move_type": MT.OUT_INVOICE, "journal_type": "SALE"},
    "purchase_order":  {"model": PurchaseOrder,  "move_type": MT.IN_INVOICE,  "journal_type": "PURCHASE"},
    "supplier_return": {"model": StockPicking,   "move_type": MT.IN_REFUND,   "journal_type": "PURCHASE"},
    "customer_return": {"model": StockPicking,   "move_type": MT.OUT_REFUND,  "journal_type": "SALE"},
}

SALE_TYPES = (MT.OUT_INVOICE, MT.OUT_REFUND)


def resolve_origin_type(origin_type):
    config = ORIGIN_TYPE_MAP.get(origin_type)
    if not config:
        raise ValidationError(f"Unsupported origin_type: {origin_type}")
    return config


def _drafted_quantity(line):
    """Quantity already claimed by open draft invoices for this source line."""
    from django.db.models import Sum
    return (
        AccountMoveLine.objects.filter(
            source_line_type=ContentType.objects.get_for_model(line),
            source_line_id=line.pk,
            line_type=AccountMoveLine.LineType.PRODUCT,
            move__state=AccountMove.State.DRAFT,
            move__move_type__in=(MT.OUT_INVOICE, MT.IN_INVOICE),
        ).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0")
    )


def get_usable_lines(lines):
    usable_lines = []
    for line in lines:
        if line.qty_invoiced > line.invoice_target_quantity:
            raise ValidationError(
                f"Line {line.id}: invoiced quantity ({line.qty_invoiced}) exceeds "
                f"invoiceable target ({line.invoice_target_quantity}) under "
                f"'{line.invoice_policy}' policy."
            )

        remaining = max(line.qty_to_invoice - _drafted_quantity(line), Decimal("0"))
        if remaining <= 0:
            continue
        usable_lines.append({"line": line, "quantity": remaining})
    return usable_lines


def _resolve_line_account(product, move_type, company, settings_map):
    """Income account for sales, expense account for purchases."""
    is_sale = move_type in SALE_TYPES
    attr = "revenue_account" if is_sale else "expense_account"           # ADJUST to your Product fields
    category = getattr(product, "category", None)
    account = getattr(product, attr, None) or getattr(category, attr, None)
    if account is None:
        account = settings_map.get(
            "default_income_account" if is_sale else "default_expense_account"  # ADJUST to your settings keys
        )
    if account is None:
        raise ValidationError(f"No {'income' if is_sale else 'expense'} account for '{product}'.")
    return account


@transaction.atomic
def to_invoice(origin_type, source, user):
    config = resolve_origin_type(origin_type)
    if not isinstance(source, config["model"]):
        raise ValidationError(
            f"Expected source of type {config['model'].__name__} for origin_type "
            f"'{origin_type}', got {type(source).__name__}."
        )

    move_type = config["move_type"]

    if getattr(source, "payment_term", None) is None:
        raise ValidationError(f"Cannot create invoice: {source} has no payment term set.")

    company = source.company
    journal = Journal.objects.filter(company=company, type=config["journal_type"]).order_by("pk").first()
    if not journal:
        raise ValidationError(f"No {config['journal_type']} journal configured for company '{company}'.")

    invoice = AccountMove.objects.create(
        state=AccountMove.State.DRAFT,
        created_by=user,
        partner=source.partner,
        currency=source.currency,
        currency_rate=getattr(source, "exchange_rate", None),   # re-snapshotted at posting
        company=company,
        journal=journal,
        fulfillment_location=getattr(source, "fulfillment_location", None),
        payment_term=source.payment_term,
        move_type=move_type,
        origin_reference=getattr(source, "reference", None) or str(source),
        origin_type=origin_type,
        origin_id=source.pk,
        issue_date=source.issue_date,
    )

    _copy_lines(source, invoice, company)
    _set_draft_totals(invoice)
    return invoice


def _copy_lines(source, invoice, company):
    lines = list(source.lines.select_for_update().all())
    usable_lines = get_usable_lines(lines)
    if not usable_lines:
        raise ValidationError(
            f"Cannot create invoice: source {source} has no remaining quantity to invoice."
        )

    settings_map = company.get_settings_dict()

    for seq, entry in enumerate(usable_lines, start=1):
        src = entry["line"]
        new_line = AccountMoveLine.objects.create(     # create() runs save() -> clean(), and gives us a pk for taxes
            move=invoice,
            line_type=AccountMoveLine.LineType.PRODUCT,
            sequence=seq * 10,
            account=_resolve_line_account(src.product, invoice.move_type, company, settings_map),
            partner=invoice.partner,
            product=src.product,
            product_uom=getattr(src, "product_uom", None),   # save() falls back to product.uom
            quant=getattr(src, "quant", None),
            description=src.description,
            quantity=entry["quantity"],
            price_unit=src.price_unit,
            discount_percent=src.discount_percent,
            debit=Decimal("0"),                             # memo line; GL is built at posting
            credit=Decimal("0"),
            source_line_type=ContentType.objects.get_for_model(src),
            source_line_id=src.pk,
        )
        new_line.taxes.set(src.taxes.all())


def _set_draft_totals(invoice):
    invoice.__dict__.pop("tax_summary", None)    # cached_property: clear before reading
    invoice.amount_untaxed = invoice.untaxed_amount
    invoice.amount_tax = invoice.total_tax
    invoice.amount_total = invoice.total_amount
    invoice.amount_residual = invoice.amount_total
    invoice.save(update_fields=["amount_untaxed", "amount_tax", "amount_total", "amount_residual"])