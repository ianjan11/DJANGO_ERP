from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountMove, AccountMoveLine, Journal
from accounting.services.account_resolver import resolve_account, invoice_line_role
from inventory.models import StockPicking
from purchases.models import PurchaseOrder
from sales.models import SalesOrder
from inventory.models import StockLocation, StockMove


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



def _fulfilled_from_moves(line):
    """Net quantity actually moved for this order line, in the line's UoM."""
    U = StockLocation.Usage
    is_sale = hasattr(line, "sales_order") or line.__class__.__name__ == "SalesOrderLine"
    fk = "sale_line" if is_sale else "purchase_line"
    out_pair = (U.INTERNAL, U.CUSTOMER) if is_sale else (U.SUPPLIER, U.INTERNAL)
    ret_pair = (U.CUSTOMER, U.INTERNAL) if is_sale else (U.INTERNAL, U.SUPPLIER)

    line_uom = line.product_uom or line.product.uom
    total = Decimal("0")
    moves = (StockMove.objects
             .filter(**{fk: line}, status=StockMove.Status.COMPLETED)
             .select_related("source_location", "dest_location", "product_uom", "product__uom"))
    for m in moves:
        qty = (m.product_uom or m.product.uom).convert_to(m.quantity, line_uom)
        pair = (m.source_location.usage, m.dest_location.usage)
        if pair == out_pair:
            total += qty
        elif pair == ret_pair:
            total -= qty
    return max(total, Decimal("0"))


def get_usable_lines(lines):
    usable_lines = []
    for line in lines:
        if line.invoice_policy in ("delivery", "receive"):
            target = _fulfilled_from_moves(line)
        else:
            target = line.quantity

        # Over-invoiced (e.g. after a return): needs a credit note, not an error.
        if line.qty_invoiced > target:
            continue

        remaining = max(target - line.qty_invoiced - _drafted_quantity(line), Decimal("0"))
        if remaining <= 0:
            continue
        usable_lines.append({"line": line, "quantity": remaining})
    return usable_lines



@transaction.atomic
def to_invoice(origin_type, source, user):
    config = resolve_origin_type(origin_type)
    if not isinstance(source, config["model"]):
        raise ValidationError(
            f"Expected source of type {config['model'].__name__} for origin_type "
            f"'{origin_type}', got {type(source).__name__}."
        )

    if getattr(source, "payment_term", None) is None:
        raise ValidationError(f"Cannot create invoice: {source} has no payment term set.")

    company = source.company
    journal = (Journal.objects
               .filter(company=company, type=config["journal_type"])
               .order_by("pk").first())
    if not journal:
        raise ValidationError(
            f"No {config['journal_type']} journal configured for company '{company}'."
        )

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
        move_type=config["move_type"],
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

    settings_map = company.get_settings_dict()   # fetched once, shared by every line

    for seq, entry in enumerate(usable_lines, start=1):
        src = entry["line"]
        account = resolve_account(
            invoice_line_role(src.product, invoice.move_type),
            company=company,
            product=src.product,
            settings_map=settings_map,
        )
        new_line = AccountMoveLine.objects.create(
            move=invoice,
            line_type=AccountMoveLine.LineType.PRODUCT,
            sequence=seq * 10,
            account=account,
            partner=invoice.partner,
            product=src.product,
            product_uom=getattr(src, "product_uom", None),
            quant=getattr(src, "quant", None),
            description=src.description,
            quantity=entry["quantity"],
            price_unit=src.price_unit,
            discount_percent=src.discount_percent,
            debit=Decimal("0"),          # memo line; GL is built at posting
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