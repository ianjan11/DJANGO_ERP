import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

logger = logging.getLogger("document.calculation")


class CalculationService:
    """
    Document-level calculation service.

    Two independent calculations happen here:
      - Pricing totals (subtotal / total_tax / total) — meaningful only for
        product lines, which price a product and carry taxes. A plain line
        (LineType.PLAIN) contributes zero here.
      - Balance (total_debit / total_credit) — meaningful for every line
        regardless of type, since debit/credit are set directly on any
        AccountMoveLine (product, plain journal, tax, receivable, rounding).

    Delegates line pricing calculations to AbstractOrderLine/PricedLineMixin
    for saved model instances, and falls back to mirroring that logic for
    unsaved dict payloads (HTMX rows before save).
    """

    # ------------------------------------------------------------------
    # 1. LINE CALCULATIONS — pricing
    # ------------------------------------------------------------------

    def calculate_line(self, item):
        """
        Calculates subtotal and tax results for a single line item.
        Handles model instances and payload dictionaries. A plain line
        (no product) contributes nothing here — its debit/credit is
        picked up separately by _line_debit_credit().
        """
        if self._is_plain(item):
            return self._zero_pricing_result()

        # Django model instance using AbstractOrderLine / PricedLineMixin
        if hasattr(item, "compute_taxes") and hasattr(item, "subtotal"):
            tax_res = item.compute_taxes()
            return {
                "subtotal": item.subtotal(),
                "total_tax": tax_res["total_tax"],
                "total_with_tax": tax_res["total_with_tax"],
                "tax_details": tax_res["lines"],
                "net_base": tax_res["base"],
            }

        # Dict / Unsaved HTMX Payload Fallback
        return self._calculate_dict_line(item)

    # ------------------------------------------------------------------
    # 2. LINE CALCULATIONS — balance contribution
    # ------------------------------------------------------------------

    def _line_debit_credit(self, item):
        """
        Returns (debit, credit) for a single line, model instance or dict.
        Applies regardless of line_type: every AccountMoveLine carries
        debit/credit whatever kind of line it is.
        """
        if isinstance(item, dict):
            debit = self._to_decimal(item.get("debit"))
            credit = self._to_decimal(item.get("credit"))
        else:
            debit = self._to_decimal(getattr(item, "debit", None))
            credit = self._to_decimal(getattr(item, "credit", None))
        return debit, credit

    # ------------------------------------------------------------------
    # 3. DOCUMENT AGGREGATION
    # ------------------------------------------------------------------

    def recalculate(self, doc_instance_or_lines) -> dict:
        """
        Full document recalculation: pricing totals (product lines only)
        plus balance (all lines).

        Returns:
            {
                "subtotal": Decimal,
                "total_tax": Decimal,
                "total": Decimal,
                "total_debit": Decimal,
                "total_credit": Decimal,
                "balance": Decimal,
                "is_balanced": bool,
                "lines": [...],
            }
        """
        lines = self._resolve_lines(doc_instance_or_lines)

        document_subtotal = Decimal("0.00")
        document_tax = Decimal("0.00")
        document_total = Decimal("0.00")
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        calculated_lines = []

        for item in lines:
            res = self.calculate_line(item)
            debit, credit = self._line_debit_credit(item)

            document_subtotal += res["subtotal"]
            document_tax += res["total_tax"]
            document_total += res["total_with_tax"]
            total_debit += debit
            total_credit += credit

            calculated_lines.append({
                "item_id": getattr(item, "id", item.get("id") if isinstance(item, dict) else None),
                "line_type": self._line_type_value(item),
                "subtotal": res["subtotal"],
                "total_tax": res["total_tax"],
                "total_with_tax": res["total_with_tax"],
                "debit": debit,
                "credit": credit,
            })

        balance = (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        result = {
            "subtotal": document_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total_tax": document_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total": document_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total_debit": total_debit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "total_credit": total_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "balance": balance,
            "is_balanced": balance == Decimal("0.00"),
            "lines": calculated_lines,
        }

        logger.info(
            "Calculations for move pk=%s: total_debit=%s, total_credit=%s, balance=%s",
            getattr(doc_instance_or_lines, "pk", None),
            result["total_debit"], result["total_credit"], result["balance"],
        )

        return result

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _is_plain(self, item):
        """
        True if this line is a non-product journal line. Checks line_type
        on both model instances and dict payloads. AccountMoveLine.LineType.PLAIN
        is the empty string '', so both '' and the payload convention "plain"
        count. Falls back to "no product_id" for line models that don't carry
        line_type at all (e.g. SalesOrderLine/PurchaseOrderLine).
        """
        if isinstance(item, dict):
            line_type = item.get("line_type")
        else:
            line_type = getattr(item, "line_type", None)

        if line_type is not None:
            value = line_type.value if hasattr(line_type, "value") else line_type
            return value in ("", "plain")

        product_id = item.get("product_id") if isinstance(item, dict) else getattr(item, "product_id", None)
        return not product_id

    def _line_type_value(self, item):
        if isinstance(item, dict):
            return item.get("line_type")
        line_type = getattr(item, "line_type", None)
        return line_type.value if hasattr(line_type, "value") else line_type

    def _zero_pricing_result(self):
        return {
            "subtotal": Decimal("0.00"),
            "total_tax": Decimal("0.00"),
            "total_with_tax": Decimal("0.00"),
            "tax_details": [],
            "net_base": Decimal("0.00"),
        }

    def _resolve_lines(self, source):
        """
        Safely retrieves line items. Since all models use 'lines',
        we standardise on 'doc.lines.all()'.
        """
        if isinstance(source, (list, tuple)):
            return source

        if hasattr(source, "lines"):
            lines_rel = source.lines
            # Pre-prefetch taxes to avoid N+1 queries during tax computation
            if hasattr(lines_rel, "prefetch_related"):
                return lines_rel.prefetch_related("taxes").all()
            if hasattr(lines_rel, "all"):
                return lines_rel.all()
            return lines_rel

        if isinstance(source, dict) and "items" in source:
            return source["items"]

        return []

    def _calculate_dict_line(self, item_dict):
        """
        Fallback line math for unsaved dictionary payloads before saving to DB.
        Mirrors AbstractOrderLine logic. Only reached for product lines —
        _is_plain() routes plain lines to _zero_pricing_result() first.
        """
        qty = self._to_decimal(item_dict.get("quantity"))
        price = self._to_decimal(item_dict.get("price_unit"))
        discount = self._to_decimal(item_dict.get("discount_percent"))

        multiplier = (Decimal("100") - discount) / Decimal("100")
        exact_subtotal = price * multiplier * qty
        subtotal_rounded = exact_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "subtotal": subtotal_rounded,
            "total_tax": Decimal("0.00"),
            "total_with_tax": subtotal_rounded,
            "tax_details": [],
            "net_base": subtotal_rounded,
        }

    @staticmethod
    def _to_decimal(value) -> Decimal:
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        stripped = str(value).strip()
        if not stripped:
            return Decimal("0")
        try:
            return Decimal(stripped)
        except InvalidOperation:
            return Decimal("0")