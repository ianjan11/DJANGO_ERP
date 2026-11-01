import logging
from decimal import InvalidOperation, Decimal
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.views.decorators.http import require_POST
from pygments.lexers import data
from django.http import Http404, JsonResponse
from accounting.events.accounting_events import create_event
from accounting.events.types import AccountingEventType

from accounting.models import  AccountMoveLine
from accounting.services.account_move_services.account_move_loader import load_account_move
from accounting.services.credit_note_service.create_credit_note_from_invoice import create_credit_from_invoice

from core.events import dispatch

from core.utils import htmx_error, htmx_success

logger = logging.getLogger('sales.invoice')


# ---------------- view ----------------
@require_POST
@login_required
def issue_credit_note_view(request, invoice_id):
    detail_url = reverse("accounting:invoice_create_or_detail", kwargs={"invoice_id": invoice_id})
    data = request.POST

    items = []
    for key, value in data.items():
        if not key.startswith('line_id_'):
            continue
        suffix = key[len('line_id_'):]
        items.append({
            "line_id": value,
            "amount": data.get(f'credit_amount_{suffix}'),  # matches the JS field name
        })

    if not items:
        return JsonResponse({"success": False, "errors": "No items found."}, status=400)

    try:
        with transaction.atomic():
            invoice = load_account_move(invoice_id, request, for_update=True)

            if not invoice.has_items():
                return JsonResponse({"success": False, "errors": "Invoice has no items."}, status=400)

            if invoice.state != invoice.State.POSTED:
                return JsonResponse({"success": False, "errors": "Invoice is not posted."}, status=400)

            lines_data = []
            line_errors = []

            for index, item in enumerate(items, start=1):
                try:
                    invoice_line = invoice.lines.get(id=item.get("line_id"))
                except (AccountMoveLine.DoesNotExist, ValueError, TypeError):
                    line_errors.append({"line": index, "error": f"Invoice line {item.get('line_id')} not found."})
                    continue

                try:
                    credit_amount = Decimal(str(item.get("amount")))
                    if credit_amount <= 0:
                        raise InvalidOperation
                except (TypeError, InvalidOperation):
                    line_errors.append({"line": index, "error": "Invalid credit amount."})
                    continue

                lines_data.append({"line": invoice_line, "amount": credit_amount})

            if line_errors:
                return JsonResponse({"success": False, "errors": line_errors}, status=400)

            credit_invoice = create_credit_from_invoice(invoice, lines_data, request.user)

            event = create_event(
                event_type=AccountingEventType.INVOICE_CREATED,
                payload={
                    "invoice_id": credit_invoice.pk,
                    "invoice_number": credit_invoice.name,
                    "partner_id": credit_invoice.partner_id,
                    "amount": str(credit_invoice.amount_total),
                    "reversed_invoice_id": invoice.pk,
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get('HX-Request') else "web",
            )
            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to issue credit note for invoice %s", invoice_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Invoice Credited Successfully",
        redirect_url=detail_url,
        target="#accounting-display",
    )

# ---------------- creation ----------------

