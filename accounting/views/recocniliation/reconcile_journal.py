from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from accounting.services.reconciliation_service.reconciliation_service import ReconciliationService

import logging



logger = logging.getLogger("accounting.reconciliation")



from core.utils import htmx_success, htmx_error


@require_POST
def reconcile_journal(request):

    redirect_url = reverse('accounting:reconciliation')

    line_ids = request.POST.getlist("line_ids")

    # --------------------------------------------------------------
    # REQUEST VALIDATION
    # --------------------------------------------------------------

    if not line_ids:
        return htmx_error(
            request,
            message="Select at least one line to reconcile.",
        )

    # --------------------------------------------------------------
    # RECONCILE
    # --------------------------------------------------------------

    service = ReconciliationService(
        company=request.company,
        line_ids=line_ids,
        user=request.user,
    )

    result = service.run()

    # --------------------------------------------------------------
    # NOTHING RECONCILED
    # --------------------------------------------------------------

    if not result["success"]:

        return htmx_error(
            request,
            message="No reconciliation could be created.",
        )

    # --------------------------------------------------------------
    # PARTIAL / SUCCESSFUL RESULT
    # --------------------------------------------------------------

    matched_count = result["matched_count"]

    if (
        result["line_errors"]
        or result["group_errors"]
        or result["match_errors"]
    ):
        return htmx_success(
            request,
            message=(
                f"{matched_count} reconciliation(s) created. "
                f"Some selected lines could not be reconciled."
            ),
        )

    # --------------------------------------------------------------
    # COMPLETE SUCCESS
    # --------------------------------------------------------------

    return htmx_success(
        request,
        message=(
            f"{matched_count} reconciliation(s) created."
        ),
        redirect_url=redirect_url,
        target="#accounting-display",
    )


@require_POST
def auto_reconcile_journal(request):

    redirect_url = reverse('accounting:reconciliation')

    # --------------------------------------------------------------
    # RECONCILE
    # --------------------------------------------------------------

    service = ReconciliationService(
        company=request.company,
        user=request.user,
    )

    result = service.run()

    # --------------------------------------------------------------
    # NOTHING RECONCILED
    # --------------------------------------------------------------

    if not result["success"]:

        return htmx_error(
            request,
            message="No reconciliation could be created.",
        )

    # --------------------------------------------------------------
    # PARTIAL / SUCCESSFUL RESULT
    # --------------------------------------------------------------

    matched_count = result["matched_count"]

    if (
        result["line_errors"]
        or result["group_errors"]
        or result["match_errors"]
    ):
        return htmx_success(
            request,
            message=(
                f"{matched_count} reconciliation(s) created. "
                f"Some selected lines could not be reconciled."
            ),
            target="#accounting-display",

        )

    # --------------------------------------------------------------
    # COMPLETE SUCCESS
    # --------------------------------------------------------------

    return htmx_success(
        request,
        message=(
            f"{matched_count} reconciliation(s) created."
        ),
        redirect_url=redirect_url,
        target="#accounting-display",

    )

