from datetime import date

from django.db.models import Sum

from ..models import AccountMoveLine, Account
from decimal import Decimal


def get_data(company, target_date):
    rows = (
        AccountMoveLine.objects
        .filter(
            move__company=company,
            date__lte=target_date,
            move__state='posted',
        )
        .values('account__code', 'account__name')
        .annotate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit'),
        )
        .order_by('account__code')
    )

    trial_balance_data = {}
    for row in rows:
        code = row['account__code']
        debit  = row['total_debit']  or Decimal('0')
        credit = row['total_credit'] or Decimal('0')
        trial_balance_data[code] = {
            'account_code': code,
            'account_name': row['account__name'],
            'total_debit':  debit,
            'total_credit': credit,
            'balance':      debit - credit,
        }

    return trial_balance_data



BALANCE_SHEET_GROUPS = ['ASSET', 'LIABILITY', 'EQUITY']
PNL_GROUPS           = ['INCOME', 'EXPENSE']


def get_balance_sheet_data(company, target_date):
    """
    Returns structured balance sheet data grouped by internal_group.

    Structure:
    {
        'ASSET':     { 'label': 'Assets',       'accounts': [...], 'total': Decimal },
        'LIABILITY': { 'label': 'Liabilities',  'accounts': [...], 'total': Decimal },
        'EQUITY':    { 'label': 'Equity',        'accounts': [...], 'total': Decimal },
        'net_income': Decimal,   # INCOME - EXPENSE (goes into equity section)
        'total_assets': Decimal,
        'total_liabilities_equity': Decimal,
        'balanced': bool,
    }
    """
    trial_balance = get_data(company, target_date)

    # Fetch all active accounts for this company with their type
    accounts = (
        Account.objects
        .filter(company=company, is_active=True)
        .select_related('account_type')
        .order_by('code')
    )

    account_map = {acc.code: acc for acc in accounts}

    sections = {
        'ASSET':     {'label': 'Assets',      'accounts': [], 'total': Decimal('0')},
        'LIABILITY': {'label': 'Liabilities', 'accounts': [], 'total': Decimal('0')},
        'EQUITY':    {'label': 'Equity',      'accounts': [], 'total': Decimal('0')},
        'INCOME':    {'label': 'Income',      'accounts': [], 'total': Decimal('0')},
        'EXPENSE':   {'label': 'Expenses',    'accounts': [], 'total': Decimal('0')},
    }

    for code, tb_row in trial_balance.items():
        account = account_map.get(code)
        if not account:
            continue

        group = account.account_type.internal_group

        # Use Account.get_balance() sign convention:
        # ASSET / EXPENSE  → debit - credit (positive = debit balance)
        # LIABILITY / EQUITY / INCOME → credit - debit (positive = credit balance)
        debit  = tb_row['total_debit']
        credit = tb_row['total_credit']

        if group in ('ASSET', 'EXPENSE'):
            balance = debit - credit
        else:
            balance = credit - debit

        if balance == Decimal('0'):
            continue  # skip zero-balance accounts

        row = {
            'account_code': code,
            'account_name': tb_row['account_name'],
            'total_debit':  debit,
            'total_credit': credit,
            'balance':      balance,
        }

        sections[group]['accounts'].append(row)
        sections[group]['total'] += balance

    # Net income = Income - Expense (retained earnings for the period)
    net_income = sections['INCOME']['total'] - sections['EXPENSE']['total']

    total_assets              = sections['ASSET']['total']
    total_liabilities_equity  = (
        sections['LIABILITY']['total'] +
        sections['EQUITY']['total'] +
        net_income
    )


    return {
        'sections':                 sections,
        'net_income':               net_income,
        'total_assets':             total_assets,
        'total_liabilities_equity': total_liabilities_equity,
        'balanced':                 total_assets == total_liabilities_equity,
        'target_date':              target_date,
    }

