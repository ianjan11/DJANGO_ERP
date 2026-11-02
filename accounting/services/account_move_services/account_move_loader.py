from django.shortcuts import get_object_or_404
from accounting.models import  AccountMove


def load_account_move(move_id, request, for_update=False):
    queryset = AccountMove.objects.filter(company=request.company)
    if for_update:
        queryset = queryset.select_for_update()

    return get_object_or_404(queryset, pk=move_id)
