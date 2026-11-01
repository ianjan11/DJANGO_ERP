from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

from django.utils.functional import cached_property

from core.models import AbstractOrderLine
from core.models.abstract_line import InvoiceableOrderLineMixin
from core.services.tax_engine import TaxCalculatorService


class PurchaseOrder(models.Model):
    """
    Mirrors Odoo's purchase.order state machine:
    draft -> sent -> (to_approve) -> purchase -> done
                                   \-> cancel
    """

    STATUS_CHOICES = (
        ("DRAFT", "RFQ"),
        ("SENT", "RFQ Sent"),
        ("TO_APPROVE", "To Approve"),   # optional, matches Odoo's double-validation flow
        ("PURCHASE", "Purchase Order"), # Odoo's "CONFIRMED" is actually state='purchase'
        ("DONE", "Locked/Done"),
        ("CANCELLED", "Cancelled"),
    )

    PAYMENT_STATE = (
        ("not_paid", "Not Paid"),
        ("partial", "Partial"),
        ("paid", "Paid"),
    )

    # Odoo calls this invoice_status: 'no', 'to invoice', 'invoiced'
    INVOICE_STATUS = (
        ("no", "Nothing to Invoice"),
        ("to_invoice", "To Invoice"),
        ("invoiced", "Fully Invoiced"),
    )

    SHIPMENT_STATUS = (
        ("NOT_RECEIVED", "Not Received"),
        ("PARTIALLY_RECEIVED", "Partially Received"),
        ("RECEIVED", "Received"),
        ("CANCELLED", "Cancelled"),
    )

    # --- Vendor / partner ---
    partner = models.ForeignKey(
        "core.Partner",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        null=True, blank=True,
    )

    reference = models.CharField(  # Odoo: name (sequence, e.g. P00001)
        max_length=50,
        db_index=True,
        null=True, blank=True,
    )

    fulfillment_location = models.ForeignKey(
        'inventory.Warehouse',
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        help_text="Warehouse fulfilling this purchase order",

    )

    issue_date = models.DateField(default=timezone.now)       # Odoo: date_order
    expected_date = models.DateField(null=True, blank=True)   # Odoo: date_planned

    product_uom = models.ForeignKey('inventory.Uom', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='+')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="DRAFT")
    shipment_status = models.CharField(
        max_length=20, choices=SHIPMENT_STATUS, default="NOT_RECEIVED"
    )
    invoice_status = models.CharField(
        max_length=20, choices=INVOICE_STATUS, default="no"
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_orders_created"
    )
    buyer = models.ForeignKey(  # Odoo: user_id
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="purchase_orders_bought", null=True, blank=True,
    )
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, related_name="purchase_orders")

    amount_untaxed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    amount_tax = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    amount_total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))

    payment_state = models.CharField(max_length=20, choices=PAYMENT_STATE, default="not_paid")
    payment_term = models.ForeignKey(
        "accounting.PaymentTerm", on_delete=models.PROTECT, related_name="supplier_payment_terms"
    )

    class Meta:
        ordering = ["-issue_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reference"],
                condition=Q(reference__isnull=False),
                name="uniq_purchase_order_reference_per_company",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "issue_date"]),
            models.Index(fields=["partner", "status"]),
        ]

    def __str__(self):
        return self.reference or f"PO #{self.pk}"



    @cached_property
    def tax_summary(self) -> dict:
        """
        Calculates taxes ONLY ONCE per instance execution.
        Subsequent calls return the cached dictionary immediately.
        """
        lines = list(self.lines.prefetch_related('taxes').all())
        return TaxCalculatorService.calculate_document_taxes(lines)

    @property
    def total_amount(self):
        return self.tax_summary['total_gross']

    @property
    def untaxed_amount(self):
        return self.tax_summary['total_untaxed']

    @property
    def total_tax(self):
        return self.tax_summary['total_tax']

    def total_profit(self):
        return sum(
            (item.profit() for item in self.lines.all() if item.profit() is not None),
            Decimal('0.00'),
        )

    def can_edit(self):
        return self.status == "DRAFT"

    def has_items(self):
        return self.lines.exists()

    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.utils import timezone

    from django.core.exceptions import ValidationError
    from django.db import transaction
    from django.utils import timezone

    @transaction.atomic
    def confirm(self):
        """
        Confirm a Purchase Order: update status/reference and create receipt transfers
        via receive_purchase().

        Raises:
            ValidationError: If the PO has no items.
            ValueError: If warehouse receipt configuration is missing.
        """
        if not self.has_items():
            raise ValidationError("Purchase order has no items.")

        if not self.reference:
            from purchases.services.creator import create_reference
            self.reference = create_reference(self.company)

        self.status = "PURCHASE"
        self.updated_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "reference",
                "updated_at",
            ]
        )

        from inventory.services.stock_Picking.procurement_engine import ReceiptLine, receive_purchase


        # 1. Filter Stockable Items
        stock_lines = [
            line for line in self.lines.select_related('product')
            if line.product.is_stockable
        ]

        if not stock_lines:
            return self

        # 2. Build Receipt Shapes & Execute Engine
        receipt_lines = [
            ReceiptLine(
                product=item.product,
                quantity=item.quantity,
                uom=getattr(item, "product_uom", item.product.uom),
                purchase_line=item,
                move_dest_ids=(
                    tuple(item.move_destinations.values_list("pk", flat=True))
                    if hasattr(item, "move_destinations")
                    else ()
                ),
                date=getattr(item, "date_planned", None),
            )
            for item in stock_lines
        ]

        # Procurement execution without local fallback
        receive_purchase(
            name=self.reference or self.name,
            company=self.company,
            warehouse=self.fulfillment_location,
            vendor=self.partner,
            lines=receipt_lines,
            purchase_order=self,
            date_planned=getattr(self, "date_planned", None),
        )

        return self


    def recompute_invoice_status(self, save=True):
        """
        Header-level invoice_status, aggregated from each line's invoice_state
        (which itself branches on the line's product.invoice_policy).
        Call this after receiving stock or posting a vendor bill.
        """
        line_states = [line.invoice_state for line in self.lines.all()]

        if not line_states or all(s == "no" for s in line_states):
            self.invoice_status = "no"
        elif all(s == "invoiced" for s in line_states):
            self.invoice_status = "invoiced"
        else:
            self.invoice_status = "to_invoice"

        if save:
            self.save(update_fields=["invoice_status", "updated_at"])
        return self.invoice_status


class PurchaseOrderLine(AbstractOrderLine, InvoiceableOrderLineMixin):
    purchase_order = models.ForeignKey(
        "purchases.PurchaseOrder", on_delete=models.CASCADE, related_name="lines"
    )

    quant = models.ForeignKey(
        'inventory.StockQuant',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    sequence = models.PositiveIntegerField(default=10)

    @property
    def _invoice_policy_field(self):
        return "purchase_method"

    class Meta:
        ordering = ["sequence", "pk"]


    def __str__(self):
        return f"{self.product} x {self.quantity}"