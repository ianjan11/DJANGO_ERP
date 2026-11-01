"""
Tests for accounting.models Tax / TaxLine (no database: instances are built unsaved with
explicit pks, and the reverse `children` manager is replaced by an in-memory fake).

Run with your normal Django runner, e.g.:
    python manage.py test accounting.tests.test_tax_models
"""
from decimal import Decimal
from itertools import count
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import models
from django.test import SimpleTestCase

from accounting.models import Account, Tax, TaxLine
from core.services.tax_engine import TaxCalculatorService
from core.tests.tax_fakes import FakeChildren

D = Decimal
_pk = count(1000)


def make(name='T', computation='PERCENT', rate='10', **kw):
    """A valid leaf tax by default; override anything. Pass kids=[...] for a group's children."""
    kids = kw.pop('kids', [])
    kw.setdefault('company_id', 1)
    kw.setdefault('pk', next(_pk))
    if computation != 'GROUP':
        kw.setdefault('account_id', 1)
    tax = Tax(name=name, computation=computation, rate=D(rate), **kw)
    tax._kids = kids
    return tax


def make_group(name='G', kids=(), **kw):
    return make(name, 'GROUP', '0', kids=list(kids), **kw)


class TaxTestCase(SimpleTestCase):
    def setUp(self):
        children = property(lambda self: FakeChildren(getattr(self, '_kids', [])))
        patcher = patch.object(Tax, 'children', children)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assertInvalid(self, tax, field):
        with self.assertRaises(ValidationError) as ctx:
            tax.clean()
        self.assertIn(field, ctx.exception.message_dict)


class TestTaxDefaultsAndChoices(SimpleTestCase):

    def test_defaults(self):
        tax = Tax()
        self.assertEqual((tax.type_tax_use, tax.computation, tax.rate), ('SALE', 'PERCENT', D('0')))
        self.assertTrue(tax.is_recoverable)
        self.assertTrue(tax.is_active)
        self.assertFalse(tax.price_include)
        self.assertFalse(tax.include_base_amount)

    def test_choice_values_match_what_the_engine_compares_against(self):
        self.assertEqual(Tax.Computation.GROUP, 'GROUP')
        self.assertEqual(Tax.Computation.FIXED, 'FIXED')
        self.assertEqual(Tax.Computation.PERCENT, 'PERCENT')
        self.assertEqual({c.value for c in Tax.TypeTaxUse}, {'SALE', 'PURCHASE', 'NONE'})

    def test_max_group_depth_matches_the_engine(self):
        self.assertEqual(Tax.MAX_GROUP_DEPTH, TaxCalculatorService.MAX_GROUP_DEPTH)

    def test_ordering(self):
        self.assertEqual(list(Tax._meta.ordering), ['sequence', 'id'])

    def test_account_is_optional_at_field_level_but_enforced_in_clean(self):
        self.assertTrue(Tax._meta.get_field('account').null)

    def test_is_recoverable_field_exists(self):
        self.assertIsInstance(Tax._meta.get_field('is_recoverable'), models.BooleanField)


class TestTaxStr(SimpleTestCase):

    def test_percent(self):
        self.assertEqual(str(make('VAT', rate='18')), 'VAT-18.00%')

    def test_fixed_has_no_percent_sign(self):
        self.assertEqual(str(make('Levy', 'FIXED', '5')), 'Levy-5.00')

    def test_group(self):
        self.assertEqual(str(make_group('Import')), 'Import (group)')


class TestTaxHelpers(TaxTestCase):

    def test_is_group(self):
        self.assertTrue(make_group().is_group)
        self.assertFalse(make().is_group)

    def test_is_capitalised_in_cost(self):
        cases = [
            ('PURCHASE', False, True),
            ('PURCHASE', True, False),
            ('NONE', False, True),
            ('SALE', False, False),
        ]
        for use, recoverable, expected in cases:
            with self.subTest(use=use, recoverable=recoverable):
                self.assertEqual(make(type_tax_use=use, is_recoverable=recoverable).is_capitalised_in_cost,
                                 expected)

    def test_group_is_never_capitalised_itself(self):
        self.assertFalse(make_group(type_tax_use='PURCHASE', is_recoverable=False).is_capitalised_in_cost)

    def test_get_account_returns_the_account(self):
        acc = Account(pk=1)
        self.assertIs(make(account=acc).get_account(), acc)

    def test_get_account_uses_refund_account_on_refunds(self):
        acc, refund = Account(pk=1), Account(pk=2)
        tax = make(account=acc, account_refund=refund)
        self.assertIs(tax.get_account(is_refund=True), refund)
        self.assertIs(tax.get_account(is_refund=False), acc)

    def test_get_account_falls_back_when_no_refund_account(self):
        acc = Account(pk=1)
        self.assertIs(make(account=acc).get_account(is_refund=True), acc)

    def test_group_has_no_account(self):
        with self.assertRaises(ValueError):
            make_group().get_account()

    def test_leaf_taxes_of_a_leaf_is_itself(self):
        leaf = make()
        self.assertEqual(leaf.leaf_taxes(), [leaf])

    def test_leaf_taxes_of_a_group_are_its_active_children_in_order(self):
        a, b = make('A', sequence=2), make('B', sequence=1)
        off = make('Off', is_active=False)
        self.assertEqual(make_group(kids=[a, b, off]).leaf_taxes(), [b, a])

    def test_leaf_taxes_flattens_nested_groups(self):
        leaf = make('Leaf')
        self.assertEqual(make_group(kids=[make_group('Inner', [leaf])]).leaf_taxes(), [leaf])

    def test_save_runs_full_clean_first(self):
        tax = make()
        with patch.object(Tax, 'full_clean') as full_clean, patch.object(models.Model, 'save') as save:
            tax.save()
        full_clean.assert_called_once_with()
        save.assert_called_once()


class TestCleanLeafTaxes(TaxTestCase):

    def test_valid_leaf_passes(self):
        make().clean()

    def test_leaf_needs_an_account(self):
        self.assertInvalid(make(account_id=None), 'account')

    def test_negative_rate_rejected(self):
        self.assertInvalid(make(rate='-1'), 'rate')

    def test_zero_rate_is_allowed(self):
        make(rate='0').clean()

    def test_tax_with_children_must_be_a_group(self):
        self.assertInvalid(make(kids=[make('Child')]), 'computation')

    def test_unsaved_tax_skips_the_children_check(self):
        tax = make(pk=None)
        tax._kids = [make('Child')]
        tax.clean()

    def test_non_recoverable_sale_tax_rejected(self):
        self.assertInvalid(make(type_tax_use='SALE', is_recoverable=False), 'is_recoverable')

    def test_non_recoverable_purchase_and_none_taxes_allowed(self):
        for use in ('PURCHASE', 'NONE'):
            with self.subTest(use=use):
                make(type_tax_use=use, is_recoverable=False).clean()


class TestCleanGroupTaxes(TaxTestCase):

    def test_valid_group_passes(self):
        make_group(kids=[make()]).clean()

    def test_group_cannot_have_a_rate(self):
        self.assertInvalid(make('G', 'GROUP', '5'), 'rate')

    def test_group_cannot_have_an_account(self):
        self.assertInvalid(make('G', 'GROUP', '0', account_id=1), 'account')

    def test_group_cannot_have_a_refund_account(self):
        self.assertInvalid(make('G', 'GROUP', '0', account_refund_id=1), 'account')


class TestCleanParent(TaxTestCase):

    def child_of(self, parent, **kw):
        return make('Child', parent_tax=parent, **kw)

    def test_valid_parent(self):
        self.child_of(make_group()).clean()

    def test_parent_must_be_a_group(self):
        self.assertInvalid(self.child_of(make('NotAGroup')), 'parent_tax')

    def test_parent_must_be_in_the_same_company(self):
        self.assertInvalid(self.child_of(make_group(company_id=2)), 'parent_tax')

    def test_use_mismatch_rejected(self):
        self.assertInvalid(self.child_of(make_group(type_tax_use='SALE'), type_tax_use='PURCHASE'), 'parent_tax')

    def test_none_is_compatible_on_either_side(self):
        self.child_of(make_group(type_tax_use='SALE'), type_tax_use='NONE').clean()
        self.child_of(make_group(type_tax_use='NONE'), type_tax_use='PURCHASE').clean()

    def test_matching_use_accepted(self):
        self.child_of(make_group(type_tax_use='PURCHASE'), type_tax_use='PURCHASE').clean()

    def test_direct_cycle_rejected(self):
        g1, g2 = make_group('G1'), make_group('G2')
        g1.parent_tax, g2.parent_tax = g2, g1
        self.assertInvalid(g1, 'parent_tax')

    def test_self_parent_rejected(self):
        g = make_group('G')
        g.parent_tax = g
        self.assertInvalid(g, 'parent_tax')

    def chain(self, length):
        """A leaf whose ancestors are `length` nested groups."""
        parent = None
        for i in range(length):
            parent = make_group(f'G{i}', parent_tax=parent)
        return self.child_of(parent)

    def test_nesting_at_the_limit_is_allowed(self):
        self.chain(Tax.MAX_GROUP_DEPTH).clean()

    def test_nesting_beyond_the_limit_rejected(self):
        self.assertInvalid(self.chain(Tax.MAX_GROUP_DEPTH + 1), 'parent_tax')


class TestTaxLine(SimpleTestCase):

    def test_line_on_a_leaf_tax_is_valid(self):
        TaxLine(tax=make(), base_amount=D('100'), tax_amount=D('10')).clean()

    def test_line_on_a_group_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            TaxLine(tax=make_group(), base_amount=D('100'), tax_amount=D('10')).clean()
        self.assertIn('tax', ctx.exception.message_dict)

    def test_line_without_a_tax_does_not_crash_clean(self):
        TaxLine(base_amount=D('100'), tax_amount=D('10')).clean()

    def test_str(self):
        self.assertEqual(str(TaxLine(tax=make('VAT'), base_amount=D('100'), tax_amount=D('10'))), 'VAT: 10')


class TestModelWorksWithTheEngine(TaxTestCase):
    """Real Tax instances (not duck-typed fakes) go through the engine unchanged."""

    def test_leaf_taxes(self):
        vat = make('VAT', rate='18', type_tax_use='PURCHASE')
        r = TaxCalculatorService.calculate_line_taxes(D('100.00'), D('1'), [vat], tax_use='PURCHASE')
        self.assertEqual((r['base'], r['total_tax']), (D('100.00'), D('18.00')))
        self.assertIs(r['lines'][0]['tax'], vat)

    def test_group_resolves_to_real_child_instances(self):
        vat = make('VAT', rate='18', sequence=1, type_tax_use='PURCHASE')
        duty = make('Duty', rate='5', sequence=2, type_tax_use='PURCHASE', is_recoverable=False)
        g = make_group('Import', [vat, duty], type_tax_use='PURCHASE')
        r = TaxCalculatorService.calculate_line_taxes(D('100.00'), D('1'), [g], tax_use='PURCHASE')
        self.assertEqual([l['tax'] for l in r['lines']], [vat, duty])
        self.assertEqual([l['tax'].is_capitalised_in_cost for l in r['lines']], [False, True])

    def test_sale_tax_rejected_on_purchase_line(self):
        with self.assertRaises(ValueError):
            TaxCalculatorService.calculate_line_taxes(D('100'), D('1'), [make(type_tax_use='SALE')],
                                                      tax_use='PURCHASE')

    def test_fixed_model_tax(self):
        levy = make('Levy', 'FIXED', '2')
        r = TaxCalculatorService.calculate_line_taxes(D('100.00'), D('5'), [levy])
        self.assertEqual(r['total_tax'], D('10.00'))
