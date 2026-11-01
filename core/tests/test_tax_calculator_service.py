"""
Unit tests for core.services.tax_engine.TaxCalculatorService (pure Python, no DB).

Structure mirrors the engine:
  0. flatten_taxes          - GROUP expansion, flag inheritance, usage validation
  1. solve_untaxed_base     - the linear solver for price-inclusive taxes
  2. calculate_line_taxes   - single-line results (percent / fixed / compound / mixed / groups)
  3. calculate_document_taxes - multi-line aggregation per concrete tax
  +  result shape and the purchase-cost use case (non-recoverable taxes)

Run with:
    python -m pytest test_tax_calculator_service.py -v
"""
import unittest
from decimal import Decimal

from core.services.tax_engine import TaxCalculatorService, _EffectiveTax
from core.tests.tax_fakes import D, FakeLine, FakeTax, fixed, group, pct

S = TaxCalculatorService


def calc(subtotal, taxes, qty='1', **kw):
    return S.calculate_line_taxes(subtotal=D(subtotal), quantity=D(qty), taxes=taxes, **kw)


def amount_of(result, name):
    return next(l['amount'] for l in result['lines'] if l['tax'].name == name)


def names(result):
    return [l['tax'].name for l in result['lines']]


def summary(r):
    return r['base'], r['total_tax'], r['total_with_tax']


# --------------------------------------------------------------------------- #
# 0. flatten_taxes
# --------------------------------------------------------------------------- #
class TestFlattenTaxes(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(S.flatten_taxes([]), [])

    def test_leaf_taxes_are_wrapped_not_changed(self):
        a = pct('10', 'A', price_include=True)
        [eff] = S.flatten_taxes([a])
        self.assertIsInstance(eff, _EffectiveTax)
        self.assertIs(eff.tax, a)
        self.assertEqual((eff.rate, eff.computation, eff.price_include, eff.include_base_amount),
                         (D('10'), 'PERCENT', True, False))

    def test_group_is_replaced_by_children_in_sequence_order(self):
        late, early = pct('1', 'Late', sequence=9), pct('2', 'Early', sequence=1)
        flat = S.flatten_taxes([group('G', [late, early])])
        self.assertEqual([e.tax.name for e in flat], ['Early', 'Late'])

    def test_group_keeps_its_position_among_regular_taxes(self):
        flat = S.flatten_taxes([pct('1', 'Before'), group('G', [pct('2', 'In')]), pct('3', 'After')])
        self.assertEqual([e.tax.name for e in flat], ['Before', 'In', 'After'])

    def test_inactive_children_are_skipped(self):
        flat = S.flatten_taxes([group('G', [pct('1', 'On'), pct('2', 'Off', is_active=False)])])
        self.assertEqual([e.tax.name for e in flat], ['On'])

    def test_group_flags_are_inherited_by_children_only(self):
        child = pct('5', 'Child')
        sibling = pct('5', 'Sibling')
        flat = S.flatten_taxes([group('G', [child], price_include=True, include_base_amount=True), sibling])
        by_name = {e.tax.name: e for e in flat}
        self.assertTrue(by_name['Child'].price_include)
        self.assertTrue(by_name['Child'].include_base_amount)
        self.assertFalse(by_name['Sibling'].price_include)
        self.assertFalse(by_name['Sibling'].include_base_amount)

    def test_child_own_flags_survive_when_group_flags_are_off(self):
        [eff] = S.flatten_taxes([group('G', [pct('5', price_include=True)])])
        self.assertTrue(eff.price_include)
        self.assertFalse(eff.include_base_amount)

    def test_flags_propagate_through_nested_groups(self):
        inner = group('Inner', [pct('5', 'Leaf')])
        [eff] = S.flatten_taxes([group('Outer', [inner], price_include=True)])
        self.assertTrue(eff.price_include)

    def test_group_own_rate_is_ignored(self):
        g = group('G', [pct('10', 'A')])
        g.rate = D('999')
        self.assertEqual(calc('100.00', [g])['total_tax'], D('10.00'))

    def test_empty_group_raises(self):
        with self.assertRaises(ValueError):
            S.flatten_taxes([group('Empty', [])])

    def test_group_with_only_inactive_children_raises(self):
        with self.assertRaises(ValueError):
            S.flatten_taxes([group('G', [pct('5', is_active=False)])])

    def test_circular_group_raises(self):
        g = group('Loop', [])
        g.children_list.append(g)
        with self.assertRaises(ValueError):
            S.flatten_taxes([g])

    def test_group_nested_exactly_at_the_limit_is_allowed(self):
        node = pct('1', 'Leaf')
        for i in range(S.MAX_GROUP_DEPTH):
            node = group(f'L{i}', [node])
        self.assertEqual([e.tax.name for e in S.flatten_taxes([node])], ['Leaf'])

    def test_group_nested_beyond_the_limit_raises(self):
        node = pct('1', 'Leaf')
        for i in range(S.MAX_GROUP_DEPTH + 1):
            node = group(f'L{i}', [node])
        with self.assertRaises(ValueError):
            S.flatten_taxes([node])

    def test_same_tax_may_appear_in_two_sibling_groups(self):
        shared = pct('5', 'Shared')
        flat = S.flatten_taxes([group('G1', [shared]), group('G2', [shared])])
        self.assertEqual(len(flat), 2)


class TestTaxUse(unittest.TestCase):

    def test_sale_tax_on_purchase_line_raises(self):
        with self.assertRaises(ValueError):
            calc('100.00', [pct('18', type_tax_use='SALE')], tax_use='PURCHASE')

    def test_purchase_tax_on_sale_line_raises(self):
        with self.assertRaises(ValueError):
            calc('100.00', [pct('18', type_tax_use='PURCHASE')], tax_use='SALE')

    def test_matching_use_is_accepted(self):
        for use in ('SALE', 'PURCHASE'):
            with self.subTest(use=use):
                self.assertEqual(calc('100.00', [pct('18', type_tax_use=use)], tax_use=use)['total_tax'],
                                 D('18.00'))

    def test_none_use_is_accepted_for_either(self):
        for use in ('SALE', 'PURCHASE'):
            with self.subTest(use=use):
                self.assertEqual(calc('100.00', [pct('18', type_tax_use='NONE')], tax_use=use)['total_tax'],
                                 D('18.00'))

    def test_no_tax_use_means_no_validation(self):
        self.assertEqual(calc('100.00', [pct('18', type_tax_use='SALE')])['total_tax'], D('18.00'))

    def test_children_are_validated_too(self):
        g = group('G', [pct('5', type_tax_use='SALE')], type_tax_use='PURCHASE')
        with self.assertRaises(ValueError):
            calc('100.00', [g], tax_use='PURCHASE')

    def test_error_message_names_the_tax(self):
        with self.assertRaisesRegex(ValueError, 'WrongTax'):
            calc('100.00', [pct('18', 'WrongTax', type_tax_use='SALE')], tax_use='PURCHASE')


# --------------------------------------------------------------------------- #
# 1. solve_untaxed_base
# --------------------------------------------------------------------------- #
class TestSolveUntaxedBase(unittest.TestCase):

    def solve(self, subtotal, taxes, qty='1'):
        return S.solve_untaxed_base(subtotal=D(subtotal), quantity=D(qty), taxes=taxes)

    def test_no_taxes_returns_subtotal(self):
        self.assertEqual(self.solve('100.00', []), (D('100.00'), D('1'), D('0')))

    def test_exclusive_taxes_do_not_shift_the_base(self):
        base, _, _ = self.solve('100.00', [pct('50')])
        self.assertEqual(base, D('100.00'))

    def test_single_inclusive_percent(self):
        base, run_coef, run_const = self.solve('110.00', [pct('10', price_include=True)])
        self.assertEqual((base, run_coef, run_const), (D('100'), D('1'), D('0')))

    def test_inclusive_non_compounding_taxes_add_up(self):
        base, _, _ = self.solve('110.00', [pct('5', price_include=True), pct('5', price_include=True)])
        self.assertEqual(base, D('100'))

    def test_inclusive_compounding_taxes_cascade_and_report_running_coef(self):
        t = lambda: pct('10', price_include=True, include_base_amount=True)
        base, run_coef, _ = self.solve('121.00', [t(), t()])
        self.assertEqual(base, D('100'))
        self.assertEqual(run_coef, D('1.21'))

    def test_inclusive_fixed_is_a_constant_scaled_by_quantity(self):
        base, _, run_const = self.solve('330.00', [fixed('10', price_include=True)], qty='3')
        self.assertEqual(base, D('300'))
        self.assertEqual(run_const, D('0'))      # not compounding, so the running constant is untouched

    def test_inclusive_fixed_that_compounds_updates_running_constant(self):
        _, _, run_const = self.solve('220.00', [fixed('20', price_include=True, include_base_amount=True)])
        self.assertEqual(run_const, D('20'))

    def test_non_positive_denominator_raises(self):
        with self.assertRaises(ValueError):
            self.solve('100.00', [pct('-100', price_include=True)])


# --------------------------------------------------------------------------- #
# 2. calculate_line_taxes
# --------------------------------------------------------------------------- #
class TestLineNoTaxes(unittest.TestCase):

    def test_no_taxes(self):
        r = calc('100.00', [])
        self.assertEqual(summary(r), (D('100.00'), D('0.00'), D('100.00')))
        self.assertEqual(r['lines'], [])

    def test_no_taxes_rounds_the_subtotal(self):
        self.assertEqual(calc('100.005', [])['base'], D('100.01'))


class TestLinePercentAndFixed(unittest.TestCase):

    def test_percent_exclusive(self):
        self.assertEqual(summary(calc('100.00', [pct('10', 'VAT10')])), (D('100.00'), D('10.00'), D('110.00')))

    def test_percent_inclusive(self):
        r = calc('110.00', [pct('10', price_include=True)])
        self.assertEqual(summary(r), (D('100.00'), D('10.00'), D('110.00')))

    def test_fixed_exclusive(self):
        self.assertEqual(summary(calc('100.00', [fixed('15')])), (D('100.00'), D('15.00'), D('115.00')))

    def test_fixed_exclusive_respects_quantity(self):
        self.assertEqual(calc('100.00', [fixed('15')], qty='3')['total_tax'], D('45.00'))

    def test_fixed_inclusive_is_not_treated_as_percent(self):
        """Price tag 1500 embeds a flat 500 fee -> base 1000 (not a 500% rate)."""
        r = calc('1500.00', [fixed('500', price_include=True)])
        self.assertEqual(summary(r), (D('1000.00'), D('500.00'), D('1500.00')))

    def test_fixed_inclusive_respects_quantity(self):
        r = calc('330.00', [fixed('10', price_include=True)], qty='3')
        self.assertEqual(summary(r), (D('300.00'), D('30.00'), D('330.00')))

    def test_zero_rate_tax_is_a_no_op(self):
        r = calc('100.00', [pct('0', price_include=True)])
        self.assertEqual(summary(r), (D('100.00'), D('0.00'), D('100.00')))
        self.assertEqual(r['lines'][0]['amount'], D('0.00'))

    def test_several_exclusive_taxes_are_each_on_the_base(self):
        r = calc('100.00', [pct('10', 'A'), pct('5', 'B')])
        self.assertEqual((amount_of(r, 'A'), amount_of(r, 'B')), (D('10.00'), D('5.00')))


class TestLineCompoundingAndMixed(unittest.TestCase):

    def test_multiple_non_compounding_inclusive_taxes_combine_additively(self):
        """110 / (1 + .05 + .05) = 100, not 110/1.05/1.05."""
        r = calc('110.00', [pct('5', price_include=True), pct('5', price_include=True)])
        self.assertEqual(summary(r), (D('100.00'), D('10.00'), D('110.00')))

    def test_compounding_inclusive_taxes(self):
        t = lambda: pct('10', price_include=True, include_base_amount=True)
        self.assertEqual(summary(calc('121.00', [t(), t()])), (D('100.00'), D('21.00'), D('121.00')))

    def test_compounding_exclusive_taxes_cascade(self):
        t = lambda n: pct('10', n, include_base_amount=True)
        r = calc('100.00', [t('A'), t('B')])
        self.assertEqual(summary(r), (D('100.00'), D('21.00'), D('121.00')))
        self.assertEqual((amount_of(r, 'A'), amount_of(r, 'B')), (D('10.00'), D('11.00')))

    def test_non_compounding_tax_ignores_earlier_compounding_one(self):
        r = calc('100.00', [pct('10', 'A', include_base_amount=True), pct('10', 'B')])
        self.assertEqual(amount_of(r, 'B'), D('10.00'))      # B stays on the original base

    def test_mixed_inclusive_and_exclusive_any_order(self):
        """Exclusive 10% service charge BEFORE inclusive 20% VAT; price tag 120."""
        r = calc('120.00', [pct('10', 'ServiceChargeExcl'), pct('20', 'VATIncl', price_include=True)])
        self.assertEqual(r['base'], D('100.00'))
        self.assertEqual(amount_of(r, 'VATIncl'), D('20.00'))
        self.assertEqual(amount_of(r, 'ServiceChargeExcl'), D('10.00'))

    def test_mixed_inclusive_then_exclusive_gives_same_amounts(self):
        r = calc('120.00', [pct('20', 'VATIncl', price_include=True), pct('10', 'ServiceChargeExcl')])
        self.assertEqual((amount_of(r, 'VATIncl'), amount_of(r, 'ServiceChargeExcl')), (D('20.00'), D('10.00')))

    def test_inclusive_percent_with_exclusive_fixed(self):
        r = calc('110.00', [pct('10', 'VAT', price_include=True), fixed('4', 'Levy')], qty='2')
        self.assertEqual((r['base'], amount_of(r, 'VAT'), amount_of(r, 'Levy')),
                         (D('100.00'), D('10.00'), D('8.00')))

    def test_fixed_inclusive_that_also_compounds_reconciles_to_subtotal(self):
        r = calc('242.00', [fixed('20', price_include=True, include_base_amount=True),
                            pct('10', price_include=True, include_base_amount=True)])
        total = sum(l['amount'] for l in r['lines'])
        self.assertEqual((r['base'] + total).quantize(D('0.01')), D('242.00'))


class TestLineRounding(unittest.TestCase):

    def test_pure_inclusive_rounding_does_not_drift_from_subtotal(self):
        self.assertEqual(calc('100.01', [pct('15', price_include=True)])['total_with_tax'], D('100.01'))

    def test_percent_tax_rounds_half_up(self):
        # 10.05 * 10% = 1.005 -> 1.01 (banker's rounding would give 1.00)
        r = calc('10.05', [pct('10', 'T')])
        self.assertEqual(amount_of(r, 'T'), D('1.01'))

    def test_amount_raw_keeps_precision_amount_is_rounded(self):
        r = calc('10.05', [pct('10', 'T')])
        self.assertEqual((r['lines'][0]['amount_raw'], r['lines'][0]['amount']), (D('1.005'), D('1.01')))

    def test_fixed_tax_is_quantised_to_four_places_then_two(self):
        r = calc('100.00', [fixed('0.12345', 'F')])
        self.assertEqual((r['lines'][0]['amount_raw'], r['lines'][0]['amount']), (D('0.1235'), D('0.12')))

    def test_total_tax_is_the_sum_of_rounded_lines(self):
        r = calc('10.05', [pct('10', 'A'), pct('10', 'B')])
        self.assertEqual(r['total_tax'], D('2.02'))
        self.assertEqual(r['total_with_tax'], D('12.07'))


class TestLineGroups(unittest.TestCase):

    def test_group_expands_into_children_not_the_group(self):
        vat, duty = pct('18', 'VAT', sequence=1), pct('5', 'Duty', sequence=2)
        r = calc('100.00', [group('Import', [vat, duty])])
        self.assertEqual([l['tax'] for l in r['lines']], [vat, duty])
        self.assertEqual(summary(r), (D('100.00'), D('23.00'), D('123.00')))

    def test_group_with_fixed_child_respects_quantity(self):
        r = calc('100.00', [group('G', [pct('10', 'P', sequence=1), fixed('3', 'F', sequence=2)])], qty='2')
        self.assertEqual((amount_of(r, 'P'), amount_of(r, 'F'), r['total_tax']), (D('10.00'), D('6.00'), D('16.00')))

    def test_price_inclusive_group_unwinds_children_additively(self):
        g = group('G', [pct('18', 'V', sequence=1), pct('5', 'D', sequence=2)], price_include=True)
        self.assertEqual(summary(calc('123.00', [g])), (D('100.00'), D('23.00'), D('123.00')))

    def test_compounding_group_cascades_children(self):
        g = group('G', [pct('10', 'A', sequence=1), pct('10', 'B', sequence=2)], include_base_amount=True)
        r = calc('100.00', [g])
        self.assertEqual([l['amount'] for l in r['lines']], [D('10.00'), D('11.00')])

    def test_inclusive_group_next_to_exclusive_tax(self):
        g = group('G', [pct('18', 'VAT')], price_include=True)
        r = calc('118.00', [g, pct('10', 'Excl')])
        self.assertEqual((r['base'], amount_of(r, 'VAT'), amount_of(r, 'Excl')),
                         (D('100.00'), D('18.00'), D('10.00')))

    def test_nested_groups_are_flattened(self):
        r = calc('100.00', [group('Outer', [group('Inner', [pct('5', 'Leaf')])])])
        self.assertEqual(names(r), ['Leaf'])
        self.assertEqual(r['total_tax'], D('5.00'))

    def test_group_is_equivalent_to_its_children_listed_directly(self):
        a, b = pct('7', 'A', sequence=1), pct('3', 'B', sequence=2, include_base_amount=True)
        via_group = calc('250.00', [group('G', [a, b])])
        direct = calc('250.00', [a, b])
        self.assertEqual(summary(via_group), summary(direct))


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #
class TestResultShape(unittest.TestCase):

    def test_result_keys(self):
        self.assertEqual(set(calc('100.00', [pct('10')])), {'base', 'total_tax', 'lines', 'total_with_tax'})

    def test_line_keys(self):
        [line] = calc('100.00', [pct('10')])['lines']
        self.assertEqual(set(line), {'tax', 'amount_raw', 'amount'})

    def test_results_hold_the_real_tax_object_never_the_wrapper(self):
        vat = pct('10', 'VAT')
        r = calc('100.00', [vat, group('G', [pct('5', 'In')])])
        for line in r['lines']:
            self.assertNotIsInstance(line['tax'], _EffectiveTax)
        self.assertIs(r['lines'][0]['tax'], vat)

    def test_amounts_are_decimals_with_two_places(self):
        r = calc('100.00', [pct('10')])
        for value in (r['base'], r['total_tax'], r['total_with_tax'], r['lines'][0]['amount']):
            self.assertIsInstance(value, Decimal)
            self.assertEqual(value, value.quantize(D('0.01')))


# --------------------------------------------------------------------------- #
# Purchase-cost use case
# --------------------------------------------------------------------------- #
class TestInventoryCostUseCase(unittest.TestCase):
    """What the costing service does: base + sum of NON-recoverable tax amounts."""

    @staticmethod
    def capitalised_cost(result):
        extra = sum((l['amount'] for l in result['lines'] if not l['tax'].is_recoverable), D('0'))
        return result['base'] + extra

    def test_recoverable_vat_is_not_capitalised(self):
        r = calc('100.00', [pct('18', 'VAT', type_tax_use='PURCHASE')], tax_use='PURCHASE')
        self.assertEqual(self.capitalised_cost(r), D('100.00'))

    def test_non_recoverable_tax_is_capitalised(self):
        r = calc('100.00', [pct('5', 'Duty', type_tax_use='PURCHASE', is_recoverable=False)], tax_use='PURCHASE')
        self.assertEqual(self.capitalised_cost(r), D('105.00'))

    def test_mixed_group_capitalises_only_the_non_recoverable_child(self):
        g = group('Import', [pct('18', 'VAT', sequence=1, type_tax_use='PURCHASE'),
                             pct('5', 'Duty', sequence=2, type_tax_use='PURCHASE', is_recoverable=False)],
                  type_tax_use='PURCHASE')
        self.assertEqual(self.capitalised_cost(calc('100.00', [g], tax_use='PURCHASE')), D('105.00'))

    def test_inclusive_non_recoverable_tax_is_added_back_to_the_base(self):
        r = calc('105.00', [pct('5', 'Duty', price_include=True, is_recoverable=False)])
        self.assertEqual((r['base'], self.capitalised_cost(r)), (D('100.00'), D('105.00')))

    def test_inclusive_recoverable_vat_is_stripped_out_of_cost(self):
        self.assertEqual(self.capitalised_cost(calc('118.00', [pct('18', 'VAT', price_include=True)])), D('100.00'))

    def test_fixed_non_recoverable_levy_scales_with_quantity(self):
        r = calc('100.00', [fixed('2', 'Levy', is_recoverable=False)], qty='5')
        self.assertEqual(self.capitalised_cost(r), D('110.00'))


# --------------------------------------------------------------------------- #
# 3. calculate_document_taxes
# --------------------------------------------------------------------------- #
class TestDocumentTaxes(unittest.TestCase):

    def test_totals_across_lines(self):
        vat = pct('10', 'VAT')
        doc = S.calculate_document_taxes([FakeLine('100.00', [vat]), FakeLine('50.00', [vat])])
        self.assertEqual((doc['total_untaxed'], doc['total_tax'], doc['total_gross']),
                         (D('150.00'), D('15.00'), D('165.00')))

    def test_tax_groups_are_aggregated_per_concrete_tax(self):
        vat, duty = pct('18', 'VAT', sequence=1), pct('5', 'Duty', sequence=2)
        g = group('Import', [vat, duty])
        doc = S.calculate_document_taxes([FakeLine('100.00', [g]), FakeLine('200.00', [g])])
        self.assertEqual({t['tax']: t['amount'] for t in doc['tax_groups']}, {vat: D('54.00'), duty: D('15.00')})

    def test_lines_expose_item_and_line_result(self):
        line = FakeLine('100.00', [pct('10')])
        [entry] = S.calculate_document_taxes([line])['lines']
        self.assertIs(entry['item'], line)
        self.assertEqual(entry['result']['total_tax'], D('10.00'))

    def test_lines_with_different_taxes(self):
        a, b = pct('10', 'A'), pct('20', 'B')
        doc = S.calculate_document_taxes([FakeLine('100.00', [a]), FakeLine('100.00', [b])])
        self.assertEqual({t['tax']: t['amount'] for t in doc['tax_groups']}, {a: D('10.00'), b: D('20.00')})

    def test_line_quantity_is_passed_to_fixed_taxes(self):
        doc = S.calculate_document_taxes([FakeLine('100.00', [fixed('15')], quantity='3')])
        self.assertEqual(doc['total_tax'], D('45.00'))

    def test_tax_use_is_passed_through_to_each_line(self):
        with self.assertRaises(ValueError):
            S.calculate_document_taxes([FakeLine('100.00', [pct('10', type_tax_use='SALE')])], tax_use='PURCHASE')

    def test_untaxed_lines_have_no_tax_groups(self):
        doc = S.calculate_document_taxes([FakeLine('100.00', [])])
        self.assertEqual((doc['total_tax'], doc['tax_groups']), (D('0.00'), []))

    def test_empty_document(self):
        doc = S.calculate_document_taxes([])
        self.assertEqual((doc['total_untaxed'], doc['total_tax'], doc['total_gross'], doc['tax_groups'], doc['lines']),
                         (D('0.00'), D('0.00'), D('0.00'), [], []))


if __name__ == '__main__':
    unittest.main()
