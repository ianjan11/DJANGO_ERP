from django.db import transaction
from core.models import Company, Country, Currency
from accounting.models import Account, Tax, Journal, FiscalPosition, AccountType, TaxGroup, PaymentTerm, PaymentTermLine
from accounting.services.localization import parser
from accounting.models import FiscalPositionTaxMapping, FiscalPositionAccountMapping
from core.models import CountryGroup




def _resolve_account(code_to_account, code, *, context):
    if not code:
        return None
    account = code_to_account.get(code)
    if account is None:
        raise ValueError(f"{context} references account_code '{code}' which doesn't exist in this chart.")
    return account
from accounting.models.company_accounts import CompanyAccountSetting, CompanyJournalSetting


VALID_ACCOUNT_KEYS = {key for key, _ in CompanyAccountSetting.SETTING_KEYS}
VALID_JOURNAL_KEYS = {key for key, _ in CompanyJournalSetting.SETTING_KEYS}


@transaction.atomic
def install_chart_of_accounts(company: Company, chart_key: str):

    chart = parser.parse_chart(chart_key)
    company.chart_key = chart_key
    company.save(update_fields=['chart_key'])

    account_rows = parser.parse_accounts(chart_key)

    # pass 1: create every account, no parent link yet
    code_to_account = {}
    for row in account_rows:
        account_type = AccountType.objects.get(code=row['account_type'])
        account = Account.objects.create(
            company=company,
            code=row['code'],
            name=row['name'],
            account_type=account_type,
            internal_type=row['internal_type'],
            allow_reconciliation=row['allow_reconciliation'],
            is_control_account=row['is_control_account'],
        )
        code_to_account[row['code']] = account

    # pass 2: wire up parent (self-FK) now that all rows exist
    for row in account_rows:
        if row['parent_code']:
            account = code_to_account[row['code']]
            account.parent = code_to_account[row['parent_code']]
            account.save(update_fields=['parent'])

    tax_rows = parser.parse_taxes(chart_key)

    # pass 1: create every tax (parent GROUP taxes and their components alike)
    name_to_tax = {}
    for row in tax_rows:
        tax_group = TaxGroup.objects.get_or_create(name=row['tax_group'])[0] if row['tax_group'] else None
        tax = Tax.objects.create(
            company=company,
            name=row['name'],
            type_tax_use=row['type_tax_use'],
            computation=row['computation'],
            rate=row['rate'],
            tax_group=tax_group,
            account=_resolve_account(
                code_to_account, row['account_code'],
                context=f"Tax '{row['name']}' account_code"
            ),
            account_refund=_resolve_account(
                code_to_account, row['account_refund_code'],
                context=f"Tax '{row['name']}' account_refund_code"
            ),
            price_include=row['price_include'],
            include_base_amount=row['include_base_amount'],
        )
        name_to_tax[row['name']] = tax

    # pass 2: wire up GROUP taxes' components (parent_tax + sequence/include_base_amount overrides)
    for row in tax_rows:
        if row['computation'] != 'GROUP' or not row['components']:
            continue
        parent = name_to_tax[row['name']]
        for comp in row['components']:
            child = name_to_tax.get(comp['tax_name'])
            if not child:
                raise ValueError(
                    f"Tax component '{comp['tax_name']}' referenced by group tax "
                    f"'{row['name']}' not found in chart '{chart_key}'."
                )
            child.parent_tax = parent
            child.sequence = comp['sequence']
            child.include_base_amount = comp['include_base_amount']
            child.save(update_fields=['parent_tax', 'sequence', 'include_base_amount'])

    code_to_journal = {}
    for row in parser.parse_journals(chart_key):
        currency = Currency.objects.get(code=row['currency_code']) if row['currency_code'] else None

        journal = Journal.objects.create(
            company=company,
            code=row['code'],
            name=row['name'],
            type=row['type'],
            currency=currency,
            default_debit_account=_resolve_account(
                code_to_account, row['default_debit_account_code'],
                context=f"Journal '{row['name']}' default_debit_account_code"
            ),
            default_credit_account=_resolve_account(
                code_to_account, row['default_credit_account_code'],
                context=f"Journal '{row['name']}' default_credit_account_code"
            ),
            suspense_account=_resolve_account(
                code_to_account, row['suspense_account_code'],
                context=f"Journal '{row['name']}' suspense_account_code"
            ),
            outstanding_receipts_account=_resolve_account(
                code_to_account, row['outstanding_receipts_account_code'],
                context=f"Journal '{row['name']}' outstanding_receipts_account_code"
            ),
            outstanding_payments_account=_resolve_account(
                code_to_account, row['outstanding_payments_account_code'],
                context=f"Journal '{row['name']}' outstanding_payments_account_code"
            ),
            requires_outstanding_reconciliation=row['requires_outstanding_reconciliation'],
            sequence=row['sequence'],
            notes=row['notes'],
        )
        code_to_journal[row['code']] = journal

    for row in parser.parse_fiscal_positions(chart_key):
        fp = FiscalPosition.objects.create(
            company=company,
            name=row['name'],
            country=Country.objects.filter(code=row['country_code']).first() if row['country_code'] else None,
            country_group=CountryGroup.objects.filter(name=row['country_group']).first() if row['country_group'] else None,
            auto_apply=row['auto_apply'],
        )

        for tm in row['tax_mappings']:
            src = name_to_tax.get(tm['src'])
            dest = name_to_tax.get(tm['dest']) if tm['dest'] else None
            if src:
                FiscalPositionTaxMapping.objects.create(
                    fiscal_position=fp, tax_src=src, tax_dest=dest
                )

        for am in row['account_mappings']:
            src = code_to_account.get(am['src'])
            dest = code_to_account.get(am['dest'])
            if src and dest:
                FiscalPositionAccountMapping.objects.create(
                    fiscal_position=fp, account_src=src, account_dest=dest
                )

    for row in parser.parse_company_settings(chart_key):
        key = row['key']

        if row['journal_code']:
            if key not in VALID_JOURNAL_KEYS:
                raise ValueError(f"Unknown journal setting key '{key}' in chart '{chart_key}'.")
            journal = code_to_journal.get(row['journal_code'])
            if journal is None:
                raise ValueError(
                    f"Company setting '{key}' references journal_code "
                    f"'{row['journal_code']}' which doesn't exist in chart '{chart_key}'."
                )
            CompanyJournalSetting.objects.create(company=company, key=key, journal=journal)
            continue

        if key not in VALID_ACCOUNT_KEYS:
            raise ValueError(
                f"Unknown company setting key '{key}' in chart '{chart_key}'. "
                f"Valid keys: {', '.join(sorted(VALID_ACCOUNT_KEYS))}"
            )
        if not row['account_code']:
            raise ValueError(f"Company setting '{key}' is missing a required account_code.")

        account = _resolve_account(
            code_to_account, row['account_code'],
            context=f"Company setting '{key}'"
        )
        CompanyAccountSetting.objects.create(company=company, key=key, account=account)

    for row in parser.parse_payment_terms(chart_key):
        term = PaymentTerm.objects.create(
            company=company,
            name=row['name'],
            note=row['note'],
        )

        has_balance_line = any(ln['computation_type'] == 'BALANCE' for ln in row['lines'])
        if not has_balance_line:
            raise ValueError(
                f"Payment term '{row['name']}' in chart '{chart_key}' has no BALANCE line — "
                f"every payment term must resolve the remaining amount somewhere."
            )

        for ln in row['lines']:
            PaymentTermLine.objects.create(
                payment_term=term,
                sequence=ln['sequence'],
                computation_type=ln['computation_type'],
                value=ln['value'],
                days=ln['days'],
                discount_days=ln['discount_days'],
                discount_percent=ln['discount_percent'],
            )



    return company