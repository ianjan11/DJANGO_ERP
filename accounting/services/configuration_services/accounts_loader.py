from django.shortcuts import get_object_or_404

from accounting.models import Payment, Account
from sales.models import SalesOrder


def load_accounts(account_id, request, for_update=False):
    """Loads account scoped to the user's company."""
    queryset = Account.objects.filter(company_id=request.company_id)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=account_id)
