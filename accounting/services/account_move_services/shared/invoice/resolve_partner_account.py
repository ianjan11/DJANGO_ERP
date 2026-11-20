from accounting.services.account_resolver import resolve_account, Role


def resolve_partner_account(invoice, partner):
    role = Role.RECEIVABLE if invoice.move_type in ("out_invoice", "out_refund") else Role.PAYABLE
    return resolve_account(role, company=invoice.company, partner=partner)