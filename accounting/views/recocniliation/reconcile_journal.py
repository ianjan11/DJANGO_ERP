from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.http.response import HttpResponseBadRequest, Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounting.models import AccountMoveLine, AccountMove
from accounting.services.account_move_services.account_move_loader import load_account_move
from accounting.services.reconciliation_service.reconciliation_service import ReconciliationService

import logging
from django.db import transaction



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





@require_POST
@login_required
def reconcile_from_invoice(request):
    invoice_id = request.POST.get("invoice_id")
    raw_ids = request.POST.get("credit_move_id", "")


    if not invoice_id or not raw_ids:
        return htmx_error(request, "Invoice and credit line are required.")

    detail_url = reverse(
        "accounting:invoice_create_or_detail", kwargs={"invoice_id": invoice_id}
    )

    try:
        move_ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
        if not move_ids:
            raise ValidationError("No valid payment or credit note selected.")

        invoice = load_account_move(invoice_id, request)

        if not request.user.is_staff and invoice.created_by != request.user:
            raise PermissionDenied

        if invoice.state != AccountMove.State.POSTED:
            raise ValidationError("Post the invoice before reconciling it.")

        # --- Invoice side: control (AR/AP) line only, not GDNI/GRNI clearing lines
        reconcilable = invoice.lines.filter(account__allow_reconciliation=True)
        control = reconcilable.filter(line_type=AccountMoveLine.LineType.RECEIVABLE)
        invoice_lines = list((control if control.exists() else reconcilable)
                             .values("id", "account_id"))
        if not invoice_lines:
            raise ValidationError("This invoice has no reconcilable line.")

        invoice_line_ids = [l["id"] for l in invoice_lines]
        account_ids = {l["account_id"] for l in invoice_lines}

        # --- Counterpart side: convert MOVE ids -> LINE ids on the same account(s)
        counter_line_ids = list(
            AccountMoveLine.objects.filter(
                move_id__in=move_ids,
                move__company=request.company,
                move__state=AccountMove.State.POSTED,
                account_id__in=account_ids,
                account__allow_reconciliation=True,
            ).values_list("id", flat=True)
        )
        if not counter_line_ids:
            raise ValidationError(
                "The selected payment/credit note has no open line on the "
                "invoice's receivable/payable account."
            )

        service = ReconciliationService(
            company=request.company,
            user=request.user,
            line_ids=invoice_line_ids + counter_line_ids,
        )
        result = service.run()

        if not result["success"]:
            reasons = (
                [str(e) for e in service.line_errors.values()]
                + [str(e) for e in service.group_errors.values()]
                + [m["detail"] for m in service.match_errors]
            )
            logger.warning("Reconcile from invoice %s failed: %s", invoice_id, reasons)
            raise ValidationError(reasons[0] if reasons
                                  else "No reconciliation could be created.")

    except ValidationError as e:
        return htmx_error(request, " ".join(e.messages), detail_url)
    except PermissionDenied:
        return htmx_error(request, "You do not have permission to reconcile this invoice.", detail_url)
    except Http404:
        raise
    except Exception:
        logger.exception("Failed to reconcile invoice %s", invoice_id)
        return htmx_error(request, "Failed to reconcile due to an internal error.", detail_url)

    return htmx_success(
        request,
        message="Reconciled successfully.",
        redirect_url=detail_url,
        target="#accounting-display",
    )














