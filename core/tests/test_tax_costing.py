"""
Tests for the tax-aware cost logic in inventory.services.valuation_and_costing_service:

  * _non_recoverable_tax            - which tax amounts are capitalised
  * get_receipt_unit_cost_document  - tax-aware unit cost in purchase-order currency
  * get_receipt_unit_cost           - same, converted to company currency
  * get_cost (manual / AVCO / FIFO) - incl. the "as of before this picking" arguments

No database: stock moves, products and purchase lines are lightweight fakes, and the move
replay (`_completed_moves`) is patched. The tax maths itself runs through the REAL engine.
"""
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.services.tax_engine import TaxCalculatorService
from inventory.services.cost_and_valuation import valuation_and_costing_service as svc
from core.tests.tax_fakes import fixed, group, pct

D = Decimal
COMPANY_CCY, USD = 'TZS', 'USD'


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeUom:
    """factor = how many base units one of this UoM is (unit=1, dozen=12)."""
    def __init__(self, factor=1):
        self.factor = D(factor)

    def convert_to(self, qty, to_uom):
        return D(str(qty)) * self.factor / to_uom.factor


UNIT, DOZEN = FakeUom(1), FakeUom(12)


class FakePurchaseLine:
    def __init__(self, quantity, subtotal, taxes=(), uom=None, currency=COMPANY_CCY, pk=7):
        self.pk, self.quantity, self._subtotal, self._taxes = pk, D(quantity), D(subtotal), list(taxes)
        if uom is not None:
            self.product_uom = uom
        self.purchase_order = SimpleNamespace(currency=currency)
        self.tax_use_seen = None

    def compute_taxes(self, tax_use=None):
        self.tax_use_seen = tax_use
        return TaxCalculatorService.calculate_line_taxes(self._subtotal, self.quantity, self._taxes, tax_use)


def make_product(product_cost='50', costing_method='average'):
    return SimpleNamespace(
        product_cost=None if product_cost is None else D(product_cost),
        uom=UNIT,
        company=SimpleNamespace(currency=COMPANY_CCY),
        get_costing_method=lambda: costing_method,
    )


def make_receipt(purchase_line, product=None, date_done=None, created_at=datetime(2026, 1, 5)):
    return SimpleNamespace(
        product=product or make_product(),
        purchase_line=purchase_line,
        purchase_line_id=getattr(purchase_line, 'pk', None),
        picking=SimpleNamespace(date_done=date_done) if date_done else None,
        created_at=created_at,
    )


VAT = lambda **kw: pct('18', 'VAT', type_tax_use='PURCHASE', **kw)
DUTY = lambda **kw: pct('5', 'Duty', type_tax_use='PURCHASE', is_recoverable=False, **kw)


# --------------------------------------------------------------------------- #
class TestNonRecoverableTax(unittest.TestCase):

    def test_no_lines(self):
        self.assertEqual(svc._non_recoverable_tax({'lines': []}), D('0'))

    def test_missing_lines_key(self):
        self.assertEqual(svc._non_recoverable_tax({}), D('0'))

    def test_none_lines(self):
        self.assertEqual(svc._non_recoverable_tax({'lines': None}), D('0'))

    def test_recoverable_taxes_are_ignored(self):
        data = {'lines': [{'tax': pct('18'), 'amount': D('18.00')}]}
        self.assertEqual(svc._non_recoverable_tax(data), D('0'))

    def test_non_recoverable_taxes_are_summed(self):
        data = {'lines': [{'tax': pct('5', is_recoverable=False), 'amount': D('5.00')},
                          {'tax': pct('18'), 'amount': D('18.00')},
                          {'tax': pct('2', is_recoverable=False), 'amount': D('2.50')}]}
        self.assertEqual(svc._non_recoverable_tax(data), D('7.50'))

    def test_works_on_real_engine_output(self):
        data = TaxCalculatorService.calculate_line_taxes(D('100'), D('1'), [VAT(), DUTY()])
        self.assertEqual(svc._non_recoverable_tax(data), D('5.00'))


class TestReceiptUnitCostDocument(unittest.TestCase):

    def cost(self, line, **kw):
        return svc.get_receipt_unit_cost_document(make_receipt(line, **kw))

    def test_no_purchase_line_falls_back_to_product_cost(self):
        self.assertEqual(self.cost(None, product=make_product('42')), (D('42'), None))

    def test_no_purchase_line_and_no_product_cost(self):
        self.assertEqual(self.cost(None, product=make_product(None)), (None, None))

    def test_untaxed_line(self):
        unit, ccy = self.cost(FakePurchaseLine(10, '1000'))
        self.assertEqual((unit, ccy), (D('100'), COMPANY_CCY))

    def test_recoverable_vat_is_not_part_of_the_cost(self):
        self.assertEqual(self.cost(FakePurchaseLine(10, '1000', [VAT()]))[0], D('100'))

    def test_non_recoverable_tax_is_added_to_the_cost(self):
        self.assertEqual(self.cost(FakePurchaseLine(10, '1000', [DUTY()]))[0], D('105'))

    def test_mixed_taxes_only_the_non_recoverable_part_counts(self):
        self.assertEqual(self.cost(FakePurchaseLine(10, '1000', [VAT(), DUTY()]))[0], D('105'))

    def test_mixed_group_only_the_non_recoverable_child_counts(self):
        g = group('Import', [VAT(sequence=1), DUTY(sequence=2)], type_tax_use='PURCHASE')
        self.assertEqual(self.cost(FakePurchaseLine(10, '1000', [g]))[0], D('105'))

    def test_inclusive_vat_is_unwound_from_the_price(self):
        # supplier price tag 118 per unit incl. 18% VAT -> cost 100
        self.assertEqual(self.cost(FakePurchaseLine(10, '1180', [VAT(price_include=True)]))[0], D('100'))

    def test_inclusive_non_recoverable_tax_stays_in_the_cost(self):
        self.assertEqual(self.cost(FakePurchaseLine(10, '1050', [DUTY(price_include=True)]))[0], D('105'))

    def test_fixed_non_recoverable_levy_scales_with_quantity(self):
        levy = fixed('2', 'Levy', type_tax_use='PURCHASE', is_recoverable=False)
        self.assertEqual(self.cost(FakePurchaseLine(10, '1000', [levy]))[0], D('102'))

    def test_cost_is_per_storage_unit_when_purchased_in_another_uom(self):
        # 2 dozen for 240 -> 24 storage units -> 10 each
        self.assertEqual(self.cost(FakePurchaseLine(2, '240', uom=DOZEN))[0], D('10'))

    def test_defaults_to_the_storage_uom_when_the_line_has_none(self):
        self.assertEqual(self.cost(FakePurchaseLine(4, '40'))[0], D('10'))

    def test_returns_the_purchase_order_currency(self):
        self.assertEqual(self.cost(FakePurchaseLine(1, '10', currency=USD))[1], USD)

    def test_taxes_are_validated_as_purchase_taxes(self):
        line = FakePurchaseLine(1, '100', [VAT()])
        self.cost(line)
        self.assertEqual(line.tax_use_seen, 'PURCHASE')

    def test_sales_tax_on_a_purchase_line_is_rejected(self):
        with self.assertRaises(ValueError):
            self.cost(FakePurchaseLine(1, '100', [pct('18', type_tax_use='SALE')]))

    def test_zero_quantity_raises(self):
        with self.assertRaises(Exception):
            self.cost(FakePurchaseLine(0, '100'))

    def test_missing_base_raises(self):
        line = FakePurchaseLine(1, '100')
        line.compute_taxes = lambda tax_use=None: {'base': None, 'lines': []}
        with self.assertRaises(Exception):
            self.cost(line)


class TestReceiptUnitCostInCompanyCurrency(unittest.TestCase):

    def test_same_currency_is_not_converted(self):
        with patch.object(svc, '_get_rate') as rate:
            cost = svc.get_receipt_unit_cost(make_receipt(FakePurchaseLine(10, '1000')))
        self.assertEqual(cost, D('100'))
        rate.assert_not_called()

    def test_foreign_currency_is_converted_at_the_receipt_date(self):
        move = make_receipt(FakePurchaseLine(10, '100', currency=USD), date_done=datetime(2026, 2, 1))
        with patch.object(svc, '_get_rate', return_value=D('2500')) as rate:
            cost = svc.get_receipt_unit_cost(move)
        self.assertEqual(cost, D('25000'))               # 10 USD each * 2500
        rate.assert_called_once_with(company=move.product.company, currency=USD, date=datetime(2026, 2, 1))

    def test_falls_back_to_move_creation_date_without_a_picking_date(self):
        move = make_receipt(FakePurchaseLine(1, '1', currency=USD), created_at=datetime(2026, 3, 3))
        with patch.object(svc, '_get_rate', return_value=D('2')) as rate:
            svc.get_receipt_unit_cost(move)
        self.assertEqual(rate.call_args.kwargs['date'], datetime(2026, 3, 3))

    def test_non_recoverable_tax_is_converted_too(self):
        move = make_receipt(FakePurchaseLine(10, '100', [DUTY()], currency=USD))
        with patch.object(svc, '_get_rate', return_value=D('2')):
            self.assertEqual(svc.get_receipt_unit_cost(move), D('21'))      # (100+5)/10 * 2

    def test_missing_rate_raises(self):
        move = make_receipt(FakePurchaseLine(1, '1', currency=USD))
        for bad in (None, 0, D('-1')):
            with self.subTest(rate=bad), patch.object(svc, '_get_rate', return_value=bad):
                with self.assertRaises(Exception):
                    svc.get_receipt_unit_cost(move)

    def test_no_cost_at_all_returns_none(self):
        self.assertIsNone(svc.get_receipt_unit_cost(make_receipt(None, product=make_product(None))))


class TestLayerUnitCost(unittest.TestCase):

    def test_receipt_with_purchase_line_uses_the_tax_aware_cost(self):
        move = SimpleNamespace(move_type='RECEIPT', purchase_line_id=1, product=make_product('999'))
        with patch.object(svc, 'get_receipt_unit_cost', return_value=D('105')) as f:
            self.assertEqual(svc._layer_unit_cost(move), D('105'))
        f.assert_called_once_with(move)

    def test_other_in_moves_use_product_cost(self):
        for move_type in ('CUSTOMER RETURN', 'ADJUSTMENT'):
            with self.subTest(move_type=move_type):
                move = SimpleNamespace(move_type=move_type, purchase_line_id=None, product=make_product('33'))
                self.assertEqual(svc._layer_unit_cost(move), D('33'))

    def test_receipt_without_purchase_line_uses_product_cost(self):
        move = SimpleNamespace(move_type='RECEIPT', purchase_line_id=None, product=make_product('33'))
        self.assertEqual(svc._layer_unit_cost(move), D('33'))


# --------------------------------------------------------------------------- #
def IN(qty, cost):
    return SimpleNamespace(move_type='RECEIPT', quantity_in_storage_uom=D(qty), unit_cost=D(cost))


def OUT(qty):
    return SimpleNamespace(move_type='SALES', quantity_in_storage_uom=D(qty), unit_cost=None)


class CostingCase(unittest.TestCase):
    def replay(self, moves):
        p1 = patch.object(svc, '_completed_moves', return_value=moves)
        p2 = patch.object(svc, '_layer_unit_cost', side_effect=lambda m: m.unit_cost)
        mock = p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        return mock


class TestGetCostGeneral(CostingCase):

    def test_manual_returns_product_cost(self):
        self.assertEqual(svc.get_cost(make_product('77', 'manual')), D('77'))

    def test_no_method_raises(self):
        with self.assertRaises(Exception):
            svc.get_cost(make_product(costing_method=None))

    def test_unknown_method_raises(self):
        with self.assertRaises(Exception):
            svc.get_cost(make_product(costing_method='lifo'))

    def test_as_of_arguments_reach_the_replay(self):
        for method in ('average', 'fifo'):
            with self.subTest(method=method):
                p = make_product('50', method)
                with patch.object(svc, '_completed_moves', return_value=[]) as moves:
                    svc.get_cost(p, 3, before=datetime(2026, 1, 1), exclude_move_ids=[1, 2])
                moves.assert_called_once_with(p, datetime(2026, 1, 1), [1, 2])


class TestAverageCost(CostingCase):

    def get(self, moves):
        self.replay(moves)
        return svc.get_cost(make_product('50', 'average'))

    def test_weighted_average_of_receipts(self):
        self.assertEqual(self.get([IN(10, 10), IN(10, 20)]), D('15'))

    def test_a_sale_does_not_change_the_moving_average(self):
        # FIFO-depleting then averaging the rest would give 16.67; true AVCO stays 15.
        self.assertEqual(self.get([IN(10, 10), IN(10, 20), OUT(5)]), D('15'))

    def test_receipt_after_a_sale_blends_at_the_running_average(self):
        # 10@10 -> sell 5 (5 left @10) -> receive 5@20 -> (50+100)/10 = 15
        self.assertEqual(self.get([IN(10, 10), OUT(5), IN(5, 20)]), D('15'))

    def test_no_moves_falls_back_to_product_cost(self):
        self.assertEqual(self.get([]), D('50'))

    def test_fully_depleted_stock_falls_back_to_product_cost(self):
        self.assertEqual(self.get([IN(10, 10), OUT(10)]), D('50'))

    def test_selling_more_than_on_hand_raises(self):
        self.replay([IN(5, 10), OUT(6)])
        with self.assertRaises(Exception):
            svc.get_cost(make_product('50', 'average'))

    def test_requested_quantity_does_not_matter_for_average(self):
        self.replay([IN(10, 10), IN(10, 20)])
        p = make_product('50', 'average')
        self.assertEqual(svc.get_cost(p, 1), svc.get_cost(p, 1000))


class TestFifoCost(CostingCase):

    def get(self, moves, qty=1, product_cost='50'):
        self.replay(moves)
        return svc.get_cost(make_product(product_cost, 'fifo'), qty)

    def test_takes_the_oldest_layer_first(self):
        self.assertEqual(self.get([IN(10, 10), IN(10, 20)], qty=5), D('10'))

    def test_spans_layers(self):
        # 10@10 + 5@20 = 200 over 15
        self.assertEqual(self.get([IN(10, 10), IN(10, 20)], qty=15), D('200') / D('15'))

    def test_earlier_sales_consume_the_oldest_layers(self):
        self.assertEqual(self.get([IN(10, 10), IN(10, 20), OUT(10)], qty=5), D('20'))

    def test_partial_layer_consumption(self):
        # sell 4 of the first layer -> 6@10 left, then 10@20; quantity 8 = 6@10 + 2@20 = 100
        self.assertEqual(self.get([IN(10, 10), IN(10, 20), OUT(4)], qty=8), D('100') / D('8'))

    def test_shortfall_beyond_layers_is_costed_at_product_cost(self):
        # 10@10 + 5@50 (product_cost) = 350 over 15
        self.assertEqual(self.get([IN(10, 10)], qty=15), D('350') / D('15'))

    def test_no_layers_falls_back_to_product_cost(self):
        self.assertEqual(self.get([], qty=5), D('50'))

    def test_fully_consumed_layers_fall_back_to_product_cost(self):
        self.assertEqual(self.get([IN(10, 10), OUT(10)], qty=5), D('50'))

    def test_selling_more_than_on_hand_raises(self):
        self.replay([IN(5, 10), OUT(6)])
        with self.assertRaises(Exception):
            svc.get_cost(make_product('50', 'fifo'), 1)

    def test_float_quantity_is_accepted(self):
        self.assertEqual(self.get([IN(10, 10)], qty=2.5), D('10'))


if __name__ == '__main__':
    unittest.main()
