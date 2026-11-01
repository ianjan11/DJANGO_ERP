def resolve_invoice_defaults(user, customer=None, invoice=None):
    """
    Returns a dict of defaults for a new invoice.

    Priority (highest → lowest):
      1. Customer preferred values     — wins if set
      2. Salesperson profile values    — wins if customer has no preference
      3. None                          — form field left blank, user must fill

    Never silently falls back to a wrong value.
    Returns None for any field not resolvable — the form will show it empty
    so the user is forced to consciously fill it in.
    """
    profile = getattr(user, 'sales_profile', None)

    def resolve(customer_val, salesperson_val):
        """Customer wins if set, otherwise salesperson, otherwise None."""
        if customer_val is not None:
            return customer_val
        return salesperson_val  # may also be None — that's fine

    if customer:

        has_items = invoice.has_items()

        if has_items:
            return {
                "fulfillment_location": invoice.fulfillment_location,
                "currency": invoice.currency,
                "payment_term": invoice.payment_term,
            }

        return {
            "fulfillment_location": resolve(
                customer.preferred_location,
                profile.default_location if profile else None,
            ),
            "currency": resolve(
                customer.preferred_currency,
                profile.default_currency if profile else None,
            ),
            "payment_term": resolve(
                customer.preferred_payment_term,
                profile.default_payment_term if profile else None,
            ),
        }

    # No customer yet — only salesperson defaults apply
    return {
        'fulfillment_location': profile.default_location     if profile else None,
        'currency':        profile.default_currency     if profile else None,
        'payment_term':    profile.default_payment_term if profile else None,
    }


