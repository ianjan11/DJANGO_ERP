from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Tuple, Protocol

class TaxProtocol(Protocol):
    rate: Decimal
    price_include: bool
    include_base_amount: bool
    computation: str  # 'PERCENT' or 'FIXED'


class _EffectiveTax:
    """
    A concrete (non-group) tax as the engine sees it. Wraps the real Tax so
    results can hand the real object back (accounts, is_recoverable, ...), while
    price_include / include_base_amount may be inherited from a parent GROUP.
    """
    __slots__ = ('tax', 'rate', 'computation', 'price_include', 'include_base_amount')

    def __init__(self, tax, price_include: bool, include_base_amount: bool):
        self.tax = tax
        self.rate = tax.rate
        self.computation = tax.computation
        self.price_include = price_include
        self.include_base_amount = include_base_amount


class TaxCalculatorService:
    MAX_GROUP_DEPTH = 5

    # ------------------------------------------------------------------
    # 0. Dedicated Purpose: Group expansion + usage validation
    # ------------------------------------------------------------------
    @classmethod
    def flatten_taxes(cls, taxes, tax_use=None, _inherit=(False, False), _seen=frozenset(), _depth=0):
        """
        Expands GROUP taxes into their active children (ordered by sequence,
        in place of the group) so the solver/forward pass only see concrete
        PERCENT / FIXED taxes.

        A group's price_include / include_base_amount flags are inherited by its
        children (OR-ed with the child's own flags).
        `tax_use` ('SALE' / 'PURCHASE'): when given, a tax of the other use raises.
        """
        inherit_pi, inherit_ib = _inherit
        flat = []
        for tax in taxes:
            if tax_use and tax.type_tax_use not in (tax_use, 'NONE'):
                raise ValueError(
                    f"Tax '{tax.name}' is a {tax.type_tax_use} tax and cannot be used on a {tax_use} line.")

            if tax.computation == 'GROUP':
                if tax.pk in _seen or _depth >= cls.MAX_GROUP_DEPTH:
                    raise ValueError(f"Tax group '{tax.name}' is circular or nested too deeply.")
                children = list(tax.children.filter(is_active=True).order_by('sequence', 'id'))
                if not children:
                    raise ValueError(f"Tax group '{tax.name}' has no active child taxes.")
                flat.extend(cls.flatten_taxes(
                    children, tax_use,
                    (inherit_pi or tax.price_include, inherit_ib or tax.include_base_amount),
                    _seen | {tax.pk}, _depth + 1))
            else:
                flat.append(_EffectiveTax(
                    tax,
                    inherit_pi or tax.price_include,
                    inherit_ib or tax.include_base_amount))
        return flat

    """
    Modular Tax Calculation Engine.
    Splits symbolic base extraction, line execution, and document aggregation
    into dedicated single-purpose methods.
    """

    # ------------------------------------------------------------------
    # 1. Dedicated Purpose: Symbolic Base Solver
    # ------------------------------------------------------------------
    @classmethod
    def solve_untaxed_base(
        cls,
        subtotal: Decimal,
        quantity: Decimal,
        taxes: List[TaxProtocol]
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Solves the linear equation for base_untaxed (X):
            subtotal = X * (1 + total_coef) + total_const
            => X = (subtotal - total_const) / (1 + total_coef)

        Returns:
            Tuple of (base_untaxed, final_run_coef, final_run_const)
        """
        run_coef, run_const = Decimal('1'), Decimal('0')
        total_coef, total_const = Decimal('0'), Decimal('0')

        for tax in taxes:
            rate_dec = tax.rate / Decimal('100')

            # Calculate this tax's line contribution co-efficients
            if tax.computation == 'FIXED':
                amt_coef = Decimal('0')
                amt_const = tax.rate * quantity
            else:  # PERCENT
                amt_coef = run_coef * rate_dec if tax.include_base_amount else rate_dec
                amt_const = run_const * rate_dec if tax.include_base_amount else Decimal('0')

            # Accumulate if price-inclusive
            if tax.price_include:
                total_coef += amt_coef
                total_const += amt_const

            # Advance running base state if compounding
            if tax.include_base_amount:
                run_coef += amt_coef
                run_const += amt_const

        denom = Decimal('1') + total_coef
        if denom <= Decimal('0'):
            raise ValueError("Inclusive tax configuration produces a non-positive base.")

        base_untaxed = (subtotal - total_const) / denom
        return base_untaxed, run_coef, run_const

    # ------------------------------------------------------------------
    # 2. Dedicated Purpose: Single-Line Execution
    # ------------------------------------------------------------------
    @classmethod
    def calculate_line_taxes(
        cls,
        subtotal: Decimal,
        quantity: Decimal,
        taxes: List[Any],
        tax_use: str = None,
    ) -> Dict[str, Any]:
        """
        Calculates untaxed base, line item tax amounts, and rounded totals for one item.
        GROUP taxes are expanded into their children first; result 'lines' list the
        concrete child taxes (each with its own account), never the group itself.
        """
        taxes = cls.flatten_taxes(taxes, tax_use) if taxes else []
        if not taxes:
            subtotal_rounded = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return {
                'base': subtotal_rounded,
                'total_tax': Decimal('0.00'),
                'lines': [],
                'total_with_tax': subtotal_rounded,
            }

        # Step 1: Extract base using dedicated solver
        base_untaxed, _, _ = cls.solve_untaxed_base(subtotal, quantity, taxes)
        running_base = base_untaxed

        # Step 2: Forward pass calculations
        tax_results = []
        summed_line_taxes = Decimal('0.00')

        for tax in taxes:
            rate_dec = tax.rate / Decimal('100')

            if tax.computation == 'FIXED':
                line_tax = (tax.rate * quantity).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            else:  # PERCENT
                calc_base = running_base if tax.include_base_amount else base_untaxed
                line_tax = calc_base * rate_dec

            if tax.include_base_amount:
                running_base += line_tax

            line_tax_rounded = line_tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            summed_line_taxes += line_tax_rounded

            tax_results.append({
                'tax': tax.tax,
                'amount_raw': line_tax,
                'amount': line_tax_rounded,
            })

        # Step 3: Final Line Reconciliation
        net_base_rounded = base_untaxed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_tax_rounded = summed_line_taxes
        total_with_tax = (net_base_rounded + total_tax_rounded).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        return {
            'base': net_base_rounded,
            'total_tax': total_tax_rounded,
            'lines': tax_results,
            'total_with_tax': total_with_tax,
        }

    # ------------------------------------------------------------------
    # 3. Dedicated Purpose: Multi-Item Document Aggregation
    # ------------------------------------------------------------------
    @classmethod
    def calculate_document_taxes(cls, items: List[Any], tax_use: str = None) -> Dict[str, Any]:
        """
        Calculates document-level tax totals across multiple order lines.
        Groups totals by tax instance for ledger journal entry creation.
        """
        document_lines = []
        tax_group_totals: Dict[Any, Decimal] = {}

        total_untaxed = Decimal('0.00')
        total_tax = Decimal('0.00')
        total_gross = Decimal('0.00')

        for item in items:
            # Delegate each item calculation to calculate_line_taxes
            line_result = cls.calculate_line_taxes(
                subtotal=item.get_subtotal(),
                quantity=getattr(item, 'quantity', Decimal('1')),
                taxes=list(item.taxes.all().order_by('sequence')),
                tax_use=tax_use,
            )

            total_untaxed += line_result['base']
            total_tax += line_result['total_tax']
            total_gross += line_result['total_with_tax']

            # Group line tax amounts for accounting summaries
            for line_tax in line_result['lines']:
                tax_obj = line_tax['tax']
                amount = line_tax['amount']
                tax_group_totals[tax_obj] = tax_group_totals.get(tax_obj, Decimal('0.00')) + amount

            document_lines.append({
                'item': item,
                'result': line_result
            })

        return {
            'total_untaxed': total_untaxed,
            'total_tax': total_tax,
            'total_gross': total_gross,
            'tax_groups': [
                {'tax': tax, 'amount': amount}
                for tax, amount in tax_group_totals.items()
            ],
            'lines': document_lines,
        }