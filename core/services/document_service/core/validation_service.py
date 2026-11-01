from decimal import Decimal, ROUND_HALF_UP
from datetime import date
import logging
from django.utils import timezone
from core.services.pricing_service import authoritative_price
from core.utils.result import fail, ok

logger = logging.getLogger("sales.invoice")


class DocumentValidationService:
    """
    Centralized validation service supporting Invoices, Sales Orders, Purchase Orders,
    supplier_invoice, and journal entries.

    Includes unit of measure (UoM) compatibility, price enforcement, header date rules,
    and plain (non-product) journal line rules.

    Stock is deliberately NOT validated here (Odoo-style permissive inventory):
    documents can be created, edited and invoiced regardless of on-hand quantity.
    Availability, reservation and negative stock are handled by the inventory layer.
    """

    LINE_VALIDATION_POLICIES = {
        "sales_invoice": {
            "pricing": True,
            "discount": True,
        },
        "sales_order": {
            "pricing": True,
            "discount": True,
        },
        "purchase_order": {
            "pricing": False,
            "discount": False,
        },
        "supplier_invoice": {
            "pricing": False,
            "discount": False,
        },
        "entry": {
            "pricing": False,
            "discount": False,
        },
    }

    DRAFT_STATUSES = {"draft", "DRAFT", "quotation", "sent", "SENT"}

    # ------------------------------------------------------------------
    # MAIN ENTRYPOINT
    # ------------------------------------------------------------------

    def validate_document(self, doc_instance, doc_type):
        """Validate entire document (Header + Lines)."""
        errors = {}
        warnings = {}
        row_errors = {}
        row_warnings = {}

        if doc_type not in self.LINE_VALIDATION_POLICIES:
            errors["doc_type"] = [f"Unsupported document type: {doc_type}"]
            return fail(errors=errors)

        # 1. Document-level state checks (partner/status/payment_state)
        doc_errors = self._validate_document_state(doc_instance)
        if doc_errors:
            errors.update(doc_errors)

        # 2. Document-level date checks (issue_date/due_date)
        date_errors = self._validate_header_dates(doc_instance)
        if date_errors:
            errors.update(date_errors)

        # 3. Extract line items safely
        lines = list(self._get_lines(doc_instance))
        policy = self.LINE_VALIDATION_POLICIES[doc_type]

        # 4. Row-level checks
        for item in lines:
            item_errors, item_warnings = self._validate_item(item, doc_instance, doc_type, policy)
            item_id = str(getattr(item, "id", getattr(item, "prefix", "new")))
            if item_errors:
                row_errors[item_id] = item_errors
            if item_warnings:
                row_warnings[item_id] = item_warnings

        if errors or row_errors:
            return fail(
                errors=errors,
                row_errors=row_errors,
                warnings=warnings,
                row_warnings=row_warnings,
            )

        return ok(warnings=warnings, row_warnings=row_warnings)

    # ------------------------------------------------------------------
    # ITEM VALIDATION
    # ------------------------------------------------------------------

    def _validate_item(self, item, doc_instance, doc_type, policy):
        """Validate a single document line item. A plain journal line
        (line_type == PLAIN, no product) gets account/debit/credit rules;
        a product line gets the UoM/pricing/discount rules."""
        errors = {}
        warnings = {}

        line_type = getattr(item, "line_type", None)
        is_plain = (
            line_type is not None
            and hasattr(item, "LineType")
            and line_type == item.LineType.PLAIN
        )

        if is_plain:
            return self._validate_plain_line(item), warnings

        product = getattr(item, "product", None)
        if not product and getattr(item, "quant", None):
            product = item.quant.product

        if not product:
            return errors, warnings

        # Pre-validate UoM Compatibility
        item_uom = getattr(item, "product_uom", None)
        product_uom = getattr(product, "uom", None)

        if item_uom and product_uom and item_uom.category_id != product_uom.category_id:
            errors["uom"] = [
                f"UoM '{item_uom.name}' is incompatible with product UoM '{product_uom.name}'."
            ]
            return errors, warnings

        if policy["pricing"]:
            errors.update(self._validate_pricing(item, doc_instance, product))

        if policy["discount"]:
            errors.update(self._validate_discount(item, product))

        return errors, warnings

    # ------------------------------------------------------------------
    # PLAIN LINE VALIDATION
    # ------------------------------------------------------------------

    def _validate_plain_line(self, item):
        """
        Rules for a non-product journal line: an account is required,
        exactly one of debit/credit must be set, neither may be negative.
        A row with nothing entered yet (debit and credit both zero) is
        left unvalidated so a freshly-added empty row doesn't error out
        before the user has typed anything.
        """
        account_id = getattr(item, "account_id", None)
        debit = getattr(item, "debit", None) or Decimal("0")
        credit = getattr(item, "credit", None) or Decimal("0")

        if not debit and not credit:
            return {}

        return self._plain_line_rule_errors(account_id, debit, credit)

    @staticmethod
    def _plain_line_rule_errors(account_id, debit, credit):
        errors = {}

        if not account_id:
            errors["account"] = ["Account is required."]

        debit = debit or Decimal("0")
        credit = credit or Decimal("0")

        if debit < 0:
            errors["debit"] = ["Debit cannot be negative."]

        if credit < 0:
            errors["credit"] = ["Credit cannot be negative."]

        if debit and credit:
            errors["debit"] = ["A line cannot contain both debit and credit."]

        if not debit and not credit:
            errors.setdefault("debit", ["Enter either a debit or credit amount."])

        return errors

    # ------------------------------------------------------------------
    # PRICING VALIDATION
    # ------------------------------------------------------------------

    def _round_money(self, value, currency=None):
        """Round half-up to the document currency's precision (default 2 dp)."""
        if value is None:
            return None
        places = getattr(currency, "decimal_places", None)
        places = 2 if places is None else places
        return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    def _validate_pricing(self, item, doc_instance, product):
        errors = {}

        item_uom = getattr(item, "product_uom", None)

        price_unit = getattr(item, "price_unit", Decimal("0"))
        discount_percent = getattr(item, "discount_percent", Decimal("0"))

        profit_margin = getattr(product, "profit_margin", Decimal("0"))
        max_discount = getattr(product, "max_discount_percent", Decimal("0"))

        # --- document / currency context ---------------------------------
        doc_currency = getattr(doc_instance, "currency", None)
        company = getattr(doc_instance, "company", None)
        doc_date = getattr(doc_instance, "issue_date", None)

        # Precision everything is compared at: the document currency's
        # decimals, falling back to 2. Same value the writer rounds to.
        places = getattr(doc_currency, "decimal_places", None) or 2

        # --- authoritative floors, via the shared helper ------------------
        # Same two computations ItemsService._resolve_authoritative_price
        # performs. If these ever drift, the writer and validator disagree.
        default_price_in_item_uom = authoritative_price(
            product,
            price_field="default_price",
            line_uom=item_uom,
            doc_currency=doc_currency,
            company=company,
            date=doc_date,
            decimal_places=places,
        )

        product_cost_base = (
            getattr(item, "product_cost", None)
            or getattr(product, "product_cost", None)
        )

        product_cost_in_item_uom = None
        if product_cost_base is not None:
            product_cost_in_item_uom = authoritative_price(
                product,
                price_field="product_cost",
                line_uom=item_uom,
                doc_currency=doc_currency,
                company=company,
                date=doc_date,
                decimal_places=places,
            )

        # --- floor 1: cost + margin, else default price -------------------
        if product_cost_in_item_uom is not None:
            minimum_price = product_cost_in_item_uom * (
                Decimal("1") + profit_margin / Decimal("100")
            )
        else:
            minimum_price = default_price_in_item_uom

        # --- floor 2: default price - max discount ------------------------
        minimum_allowed_price = default_price_in_item_uom * (
            Decimal("1") - max_discount / Decimal("100")
        )

        # --- comparison values --------------------------------------------
        price_unit_r = self._round_money(price_unit, doc_currency)
        minimum_price_r = self._round_money(minimum_price, doc_currency)

        discounted_unit_price = (
            item.get_discounted_unit_price()
            if hasattr(item, "get_discounted_unit_price")
            else price_unit * ((Decimal("100") - discount_percent) / Decimal("100"))
        )
        discounted_r = self._round_money(discounted_unit_price, doc_currency)
        minimum_allowed_r = self._round_money(minimum_allowed_price, doc_currency)

        # --- checks -------------------------------------------------------
        if discount_percent == Decimal("0") and price_unit_r < minimum_price_r:
            errors["price_unit"] = [
                f"Price ({price_unit_r}) is below the minimum allowed unit price ({minimum_price_r})."
            ]

        if discounted_r < minimum_allowed_r:
            errors["discounted_price"] = [
                f"Selling price after discount ({discounted_r}) cannot be below {minimum_allowed_r}."
            ]

        return errors

    # ------------------------------------------------------------------
    # DISCOUNT VALIDATION
    # ------------------------------------------------------------------

    def _validate_discount(self, item, product):
        errors = {}
        discount_percent = getattr(item, "discount_percent", Decimal("0"))
        max_discount = getattr(product, "max_discount_percent", Decimal("100"))

        if discount_percent > max_discount:
            errors["discount_percent"] = [
                f"Maximum discount allowed for {product.name} is {max_discount}%."
            ]

        return errors

    # ------------------------------------------------------------------
    # WORKFLOW STATE VALIDATION
    # ------------------------------------------------------------------

    def _validate_document_state(self, doc_instance):
        errors = {}

        partner_id = getattr(doc_instance, "partner_id", None) or getattr(doc_instance, "partner", None)
        if not partner_id:
            errors["partner"] = ["Document must have a partner selected."]

        status = getattr(doc_instance, "status", getattr(doc_instance, "state", None))
        if status and status not in self.DRAFT_STATUSES:
            errors["status"] = [f"Document in state '{status}' cannot be modified."]

        payment_state = getattr(doc_instance, "payment_state", None)
        if payment_state in {"paid", "partial"}:
            errors["payment_status"] = ["Paid or partially paid documents cannot be modified."]

        return errors

    # ------------------------------------------------------------------
    # HEADER DATE VALIDATION
    # ------------------------------------------------------------------

    def _validate_header_dates(self, doc_instance):
        errors = {}

        date_value = getattr(doc_instance, "issue_date", None)

        if not date_value:
            errors["issue_date"] = ["Date is required."]
        elif not isinstance(date_value, date):
            errors["issue_date"] = ["Enter a valid date."]
        elif date_value > timezone.now().date():
            errors["issue_date"] = ["Date cannot be in the future."]

        due_date = getattr(doc_instance, "due_date", None)

        if due_date and date_value and isinstance(date_value, date) and due_date < date_value:
            errors["due_date"] = ["Due date cannot be earlier than the issue date."]

        expected_date = getattr(doc_instance, "expected_date", None)

        if expected_date and date_value and isinstance(date_value, date) and expected_date < date_value:
            errors["expected_date"] = ["Expected Date cannot be earlier than the issue date."]

        return errors

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _get_lines(self, doc_instance):
        """Standardized line extractor."""
        lines_rel = getattr(doc_instance, "lines", getattr(doc_instance, "items", None))
        if lines_rel is None:
            return []
        if hasattr(lines_rel, "all"):
            return lines_rel.all()
        return lines_rel