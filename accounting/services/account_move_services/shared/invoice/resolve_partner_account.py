from django.core.exceptions import ValidationError

from accounting.services.account_move_services.shared.account_utils import assert_reconcilable, assert_same_company, \
    get_company_account
from accounting.services.account_move_services.shared.invoice.source_config import get_config


def resolve_partner_account(invoice, partner):

    config = get_config(invoice.move_type)


    if not partner:
        raise ValidationError(
            "Invoice requires an accounting partner."
        )


    partner_account_type = config["partner_account"]
    company_account_key = config["company_account"]

    if partner_account_type == "RECEIVABLE":

        partner_account = partner.account_receivable

        validation_type = "receivable"
        label = "Receivable account"

    elif partner_account_type == "PAYABLE":

        partner_account = partner.account_payable

        validation_type = "payable"
        label = "Payable account"

    else:
        raise ValidationError(
            f"Unsupported partner account type: "
            f"{partner_account_type}"
        )

    # Partner override first.
    #
    # If none exists, use company default.
    partner_account = (
        partner_account
        or get_company_account(
            invoice.company,
            company_account_key,
        )
    )

    if not partner_account:
        raise ValidationError(
            f"No {validation_type} account configured for "
            f"this partner/company."
        )

    assert_reconcilable(
        partner_account,
        validation_type,
    )

    assert_same_company(
        partner_account,
        invoice.company,
        label,
    )


    return partner_account