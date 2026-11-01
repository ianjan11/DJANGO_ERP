# accounting/l10n/parser.py
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

L10N_ROOT = Path(__file__).parent.parent.parent / 'l10n'


def parse_chart(chart_code: str) -> dict:
    root = ET.parse(L10N_ROOT / chart_code / 'chart.xml').getroot()
    return {
        'name': root.findtext('name'),
        'country_code': root.findtext('country_code'),
        'currency_code': root.findtext('currency_code'),
        'code_digits': int(root.findtext('code_digits', default='6')),
    }


def parse_accounts(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'accounts.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    return [
        {
            'code': el.get('code'),
            'account_type': el.get('account_type'),
            'internal_type': el.get('internal_type', 'other'),
            'parent_code': el.get('parent'),
            'allow_reconciliation': el.get('allow_reconciliation', 'false').lower() == 'true',
            'is_control_account': el.get('is_control_account', 'false').lower() == 'true',
            'name': el.text.strip(),
        }
        for el in root.findall('account')
    ]

def parse_taxes(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'taxes.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    taxes = []
    for el in root.findall('tax'):
        taxes.append({
            'name': el.get('name'),
            'type_tax_use': el.get('type_tax_use', 'SALE'),
            'computation': el.get('computation', 'PERCENT'),
            'rate': Decimal(el.get('rate', '0')),
            'tax_group': el.get('tax_group') or None,
            'account_code': el.get('account_code'),
            'account_refund_code': el.get('account_refund_code') or None,
            'price_include': el.get('price_include', 'false').lower() == 'true',
            'include_base_amount': el.get('include_base_amount', 'false').lower() == 'true',
            'components': [
                {
                    'tax_name': c.get('tax'),
                    'sequence': int(c.get('sequence', '10')),
                    'include_base_amount': c.get('include_base_amount', 'false').lower() == 'true',
                }
                for c in el.findall('component')
            ],
        })
    return taxes

def parse_journals(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'journals.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    return [
        {
            'code': el.get('code'),
            'name': el.get('name'),
            'type': el.get('type'),
            'currency_code': el.get('currency_code') or None,
            'default_debit_account_code': el.get('default_debit_account_code') or None,
            'default_credit_account_code': el.get('default_credit_account_code') or None,
            'suspense_account_code': el.get('suspense_account_code') or None,
            'outstanding_receipts_account_code': el.get('outstanding_receipts_account_code') or None,
            'outstanding_payments_account_code': el.get('outstanding_payments_account_code') or None,
            'requires_outstanding_reconciliation':
                el.get('requires_outstanding_reconciliation', 'false').lower() == 'true',
            'sequence': int(el.get('sequence', '1')),
            'notes': el.get('notes') or None,
        }
        for el in root.findall('journal')
    ]

def parse_fiscal_positions(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'fiscal_positions.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    positions = []
    for el in root.findall('fiscal_position'):
        positions.append({
            'name': el.get('name'),
            'country_code': el.get('country_code') or None,
            'country_group': el.get('country_group') or None,
            'auto_apply': el.get('auto_apply', 'true').lower() == 'true',
            'tax_mappings': [
                {'src': m.get('src'), 'dest': m.get('dest') or None}
                for m in el.findall('tax_mapping')
            ],
            'account_mappings': [
                {'src': m.get('src'), 'dest': m.get('dest')}
                for m in el.findall('account_mapping')
            ],
        })
    return positions

def parse_company_settings(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'company_settings.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    return [
        {
            'key': el.get('key'),
            'account_code': el.get('account_code') or None,
            'journal_code': el.get('journal_code') or None,
        }
        for el in root.findall('setting')
    ]

def parse_payment_terms(chart_key: str) -> list[dict]:
    path = L10N_ROOT / chart_key / 'payment_terms.xml'
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    terms = []
    for el in root.findall('payment_term'):
        terms.append({
            'name': el.get('name'),
            'note': el.get('note', ''),
            'lines': [
                {
                    'sequence': int(ln.get('sequence', '10')),
                    'computation_type': ln.get('computation_type', 'BALANCE'),
                    'value': Decimal(ln.get('value', '0')),
                    'days': int(ln.get('days', '0')),
                    'discount_days': int(ln.get('discount_days')) if ln.get('discount_days') else None,
                    'discount_percent': Decimal(ln.get('discount_percent')) if ln.get('discount_percent') else None,
                }
                for ln in el.findall('line')
            ],
        })

    return terms


