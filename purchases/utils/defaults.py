def resolve_purchase_defaults(user, supplier=None, purchase=None):

    company = getattr(user, 'company', None)

    def resolve(supplier_val, company_val):
        """supplier wins if set, otherwise company, otherwise None."""
        if supplier_val is not None:
            return supplier_val
        return company_val

    company_currency = getattr(company, 'currency', None) if company else None
    company_payment_term = getattr(company, 'payment_term', None) if company else None

    if supplier:

        has_items = purchase.has_items()

        if has_items:
            return {
                "currency": purchase.currency,
                "payment_term": purchase.payment_term,
            }

        return {
            'currency': resolve(supplier.preferred_currency, company_currency),
            'payment_term': resolve(supplier.preferred_payment_term, company_payment_term),
        }

    return {
        'currency': company_currency,
        'payment_term': company_payment_term,
    }