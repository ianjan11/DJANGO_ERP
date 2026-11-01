import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from pygments.lexers import data
from django.shortcuts import  render, redirect
from django.http import HttpResponse, HttpResponseBadRequest, Http404
from accounting.events.accounting_events import create_event
from accounting.events.types import AccountingEventType
from accounting.forms import PaymentForm, MoveForm, MoveLineFormSet
from accounting.models import  Payment, AccountMove, AccountMoveLine
from accounting.services import reverse_move, create_payload
from accounting.services.account_move_services.account_move_loader import load_account_move
from accounting.services.account_move_services.reverse_service import reverse_qty_invoiced
from accounting.services.invoice.invoice_post import post_invoice, post_refund_invoices
from accounting.services.invoice.invoice_state_service import InvoiceStateService
from accounting.services.invoice.creator import create_invoice
from core.events import dispatch
from core.services.document_service.document_service import DocumentService
from core.services.document_service.presentation.htmx_swap_service import UIResponseService
from core.services.document_service.quant_service import resolve_warehouse, pre_resolve
from core.services.document_service.core.payload_builder import build_payload
from core.utils import htmx_error, htmx_success
from inventory.models import StockQuant, StockLocation, Warehouse, StockPicking
import json


logger = logging.getLogger('sales.invoice')


INVOICE_TYPE_REDIRECTS = {
    AccountMove.MoveType.IN_INVOICE: "accounting:vendor_invoices",
    AccountMove.MoveType.IN_REFUND: "accounting:vendor_credit_notes",
    AccountMove.MoveType.OUT_REFUND: "accounting:customer_credit_notes",
    AccountMove.MoveType.OUT_INVOICE: "accounting:customer_invoices",
}


def _build_context(request, invoice, header_form, formset):
    invoice_id = invoice.id if invoice else None
    partner = invoice.partner if invoice else None
    company = invoice.company if invoice else getattr(request, "company", None)
    invoice_type = getattr(invoice, "move_type", None)

    # 1. Stock Location Quants
    fulfillment_location = getattr(invoice, "fulfillment_location", None) if invoice else None

    if fulfillment_location and fulfillment_location.view_location:
        # Get all descendant locations under the warehouse's root view_location
        location_ids = StockLocation.objects.filter(
            parent_path__startswith=fulfillment_location.view_location.parent_path
        ).values_list("id", flat=True)

        quants = StockQuant.objects.filter(
            location_id__in=location_ids
        ).select_related("product", "location")
    else:
        quants = StockQuant.objects.none()

    # 2. Invoice Lines (Paginator)
    if invoice:
        items_qs = invoice.lines.all().select_related("product").order_by("id")
    else:
        items_qs = AccountMoveLine.objects.none()

    paginator = Paginator(items_qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    # 3. Linked Credit Notes / Refunds
    # FIXED: Uses reversed_invoice_id to avoid "Must be Invoice instance" ValueError
    refund_types = ("out_refund", "in_refund")
    if invoice_id:
        credit_notes = (
            AccountMove.objects.filter(
                reversal_of=invoice_id,
            )
            .select_related("partner")
            .order_by("-issue_date", "-pk")
        )
    else:
        credit_notes = AccountMove.objects.none()

    # 4. Partner Type Mapping
    partner_type = ""
    if invoice_type in ("out_invoice", "out_refund"):
        partner_type = "customer"
    elif invoice_type in ("in_refund", "in_invoice"):
        partner_type = "supplier"

    # 5. Outstanding Prepayments
    if partner and company:
        payment_partner_type = "customer" if partner_type == "customer" else "supplier"
        outstanding_payments = Payment.objects.filter(
            is_prepayment=True,
            partner=partner,
            company=company,
            state="posted",
            payment_type="INCOMING" if partner_type == "customer" else "OUTGOING",
            partner_type=payment_partner_type,
        ).order_by("date")
    else:
        outstanding_payments = Payment.objects.none()

    credit_lines = invoice.lines.filter(
        line_type = AccountMoveLine.LineType.PRODUCT
    )

    return {
        "invoice": invoice,
        "header_form": header_form,
        "formset": formset,
        "quant": quants,
        "items": page_obj,
        "payment_form": PaymentForm(user=request.user, company=request.company),
        "is_new": invoice is None or invoice_id is None,
        "outstanding_payments": outstanding_payments,
        "credit_notes": credit_notes,
        "partner_type": partner_type,
        "credit_lines": credit_lines,
    }

@login_required
def invoice_create_or_detail(request, invoice_id=None):

    # ─────────────────────────────────────
    # CREATE FLOW
    # ─────────────────────────────────────
    if not invoice_id:
        invoice_type = request.GET.get("invoice_type")

        # Fallback redirect target if creation fails or type is invalid
        fallback_url = INVOICE_TYPE_REDIRECTS.get(
            invoice_type, "accounting:customer_invoices"
        )

        if not invoice_type or invoice_type not in INVOICE_TYPE_REDIRECTS:
            messages.error(request, "Invalid or missing invoice type.")
            return redirect(fallback_url)

        try:
            with transaction.atomic():
                # 1. Instantiate draft invoice via service
                invoice = create_invoice(request, invoice_type=invoice_type)

                # 2. Record creation event with the correct newly assigned invoice.id
                event = create_event(
                    event_type=AccountingEventType.INVOICE_CREATED,
                    user_id=request.user.id,
                    source="htmx" if request.headers.get("HX-Request") else "web",
                    payload={"invoice_id": invoice.id},  # FIXED: Was invoice_id (None)
                )

                transaction.on_commit(lambda: dispatch(event))

        except Exception as e:
            logger.exception("Failed to create invoice of type '%s': %s", invoice_type, e)
            messages.error(request, "Failed to initialize draft document. Please try again.")
            return htmx_error(request,"Failed to initialize draft document. Please try again.")

        # Redirect to load flow for the newly created draft
        return redirect("accounting:invoice_create_or_detail", invoice_id=invoice.id)

    # ─────────────────────────────────────
    # LOAD / DETAIL FLOW
    # ─────────────────────────────────────
    invoice = load_account_move(invoice_id, request)
    move = invoice

    header_form = MoveForm(
        request.POST or None,
        company=request.company,
        instance=move,
    )

    formset = MoveLineFormSet(
        request.POST or None,
        instance=move,
        form_kwargs={"doc": invoice},
        prefix="items",
    )

    context = _build_context(
        request=request,
        invoice=invoice,
        header_form=header_form,
        formset=formset,
    )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "accounting/move_templates/partials/move_detail_partial.html",
            context,
        )

    return render(request, "accounting/move_templates/move_detail.html", context)

@login_required
def invoice_item_row(request, invoice_id):

    invoice = load_account_move(invoice_id, request)

    partner_id = invoice.partner_id

    if not partner_id:
        return htmx_error(request, "Please Select Partner first and try again.")


    prefix = request.GET.get('prefix', 'items')
    total_forms = int(request.GET.get('total_forms', 0))

    move = invoice

    formset = MoveLineFormSet(
        instance=move,
        prefix=prefix,
        form_kwargs={"doc": invoice},
    )

    form = formset.empty_form
    form.prefix = f"{prefix}-{total_forms}"

    html = render_to_string(
        'accounting/move_templates/partials/move_item_row.html',
        {'form': form, 'invoice': invoice},
        request=request,
    )
    return HttpResponse(html)

@require_POST
def invoice_update(request):
    invoice_id = request.POST.get("invoice_id")


    if not invoice_id:
        return HttpResponseBadRequest("Missing invoice_id")

    invoice = load_account_move(invoice_id, request, for_update=True)

    if invoice.move_type in ['out_invoice', 'out_refund']:
        try:
            payload, dropped_unsaved_rows = build_payload(request.POST, doc_type="sales_invoice")

        except ValidationError as e:
            return htmx_error(
                message=e.message,
                request=request,
            )

    else:
        payload, dropped_unsaved_rows = build_payload(request.POST, doc_type="supplier_invoice")


    # 2. HAND OFF TO ORCHESTRATOR
    try:
        context = DocumentService().apply_state(
            doc_instance=invoice,
            payload=payload,
            dropped_unsaved_rows=dropped_unsaved_rows,
            request=request,
            user=request.user,
        )
    except Exception:
        logger.exception("apply_state failed for invoice_id=%s", invoice_id)
        raise

    return UIResponseService().render(request=request, payload=context)

def invoice_totals(request, invoice_id):
    invoice = load_account_move(invoice_id, request)
    return render(request, 'accounting/move_templates/partials/move_totals.html', {'invoice': invoice})

@require_POST
@login_required
def post_invoice_view(request, invoice_id):

    detail_url = reverse("accounting:invoice_create_or_detail", kwargs={"invoice_id": invoice_id})

    credit_types = ("in_refund", "out_refund")

    try:
        with transaction.atomic():

            invoice = load_account_move(invoice_id, request, for_update=True)

            if not invoice.has_items():
                return htmx_error(request, "Invoice has no items.", detail_url)

            state_service = InvoiceStateService()

            result = state_service.transition(invoice, state_service.POSTED)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This Invoice cannot be posted right now."
                )

            if invoice.move_type in credit_types:
                post_refund_invoices(invoice, request.user)
            else:
                post_invoice(invoice, request.user)

            event = create_event(
                event_type=AccountingEventType.INVOICE_POSTED,
                payload={
                    "invoice_id": invoice.pk,
                    "invoice_number": invoice.name,
                    "partner_id": invoice.partner_id,
                    "amount": str(invoice.total_amount),
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get('HX-Request') else "web",
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        # e.message_dict or e.message will automatically be parsed by htmx_error!
        return htmx_error(request, e.message if hasattr(e, 'message') else str(e), detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to post invoice %s", invoice_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Invoice Posted Successfully",
        redirect_url=detail_url,
        target="#accounting-display",
    )

@login_required
def cancel_invoice(request, invoice_id):
    detail_url = reverse(
        "accounting:invoice_create_or_detail",
        kwargs={"invoice_id": invoice_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock invoice
            invoice = load_account_move(
                invoice_id,
                request=request,
                for_update=True,
            )

            # 2. Basic document permission
            if (
                not request.user.is_staff
                and invoice.created_by != request.user
            ):
                raise PermissionDenied

            state_service = InvoiceStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = invoice.state

            # 4. Authorization based on original state
            #
            # Normal users may cancel only invoices that are
            # still in the normal editable workflow.
            #
            # Adjust these states if your invoice workflow allows
            # additional user-level cancellation states.
            if not request.user.is_staff:
                if previous_state != state_service.DRAFT:
                    raise PermissionDenied(
                        "You are not allowed to cancel this invoice."
                    )

            # 5. State service performs ALL business validation
            result = state_service.transition(
                invoice,
                state_service.CANCELLED,
            )

            if not result.get("success"):
                errors = result.get("errors")

                if isinstance(errors, dict):
                    messages = []

                    for field_errors in errors.values():
                        messages.extend(field_errors)

                    raise ValidationError(
                        messages
                        or "This invoice cannot be cancelled right now."
                    )

                raise ValidationError(
                    errors
                    or "This invoice cannot be cancelled right now."
                )

            # 6. Administrative accounting reversal
            #
            # Once an AccountMove exists, cancellation requires
            # administrative permission because the posted GL entry
            # must be reversed.
            reversal_move = None

            if invoice_id:

                if not request.user.is_staff:
                    raise PermissionDenied(
                        "Administrative permission is required "
                        "to reverse the posted accounting entry."
                    )

                # Never create a second reversal
                if invoice.reversal_of_id:
                    raise ValidationError(
                        "This invoice already has an accounting reversal."
                    )

                reversal_payload = create_payload(
                    ref=invoice.name,
                    reason="cancelled",
                    amount=str(invoice.amount_total),
                    source="move",
                    origin_id=invoice.pk,
                    origin_type="invoice",
                )

                reversal_move = reverse_move(
                    reversal_payload,
                    request.user,
                )

                invoice.reversal_of = reversal_move

                active_deliveries = (
                    StockPicking.objects
                    .select_for_update()
                    .filter(account_move=invoice)
                    .exclude(status=StockPicking.Status.CANCELLED)
                )


                if (
                        request.user.is_staff
                        and previous_state == state_service.POSTED
                ):
                    for delivery in active_deliveries:
                        delivery.cancel()


            # 7. Persist invoice state
            #
            # transition() already changed:
            #
            # invoice.status = CANCELLED
            #
            update_fields = ["state"]

            if reversal_move:
                update_fields.append("reversal_of")

            invoice.save(update_fields=update_fields)

            reverse_qty_invoiced(invoice)

            # 8. Event
            event = create_event(
                event_type=AccountingEventType.INVOICE_CANCELLED,
                payload={
                    "invoice_id": invoice.pk,
                    "invoice_number": invoice.name,
                    "partner_id": invoice.partner_id,
                    "previous_state": previous_state,
                    "new_state": state_service.CANCELLED,
                    "account_move_reversed": bool(
                        reversal_move
                    ),
                    "reversal_move_id": (
                        reversal_move.pk
                        if reversal_move
                        else None
                    ),
                },
                user_id=request.user.pk,
                source=(
                    "htmx"
                    if request.headers.get("HX-Request")
                    else "web"
                ),
            )

            transaction.on_commit(
                lambda: dispatch(event)
            )

    except ValidationError as e:
        if hasattr(e, "messages"):
            message = " ".join(e.messages)
        else:
            message = str(e)

        return htmx_error(
            request,
            message,
            detail_url,
        )

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to cancel this invoice.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to cancel invoice %s",
            invoice_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Invoice cancelled successfully.",
        redirect_url=detail_url,
        target="#invoice-display",
    )

@login_required
def reset_invoice(request, invoice_id):
    detail_url = reverse(
        "accounting:invoice_create_or_detail",
        kwargs={"invoice_id": invoice_id},
    )

    try:
        with transaction.atomic():

            # 1. Load and lock invoice
            invoice = load_account_move(
                invoice_id,
                request=request,
                for_update=True,
            )

            # 2. Basic document permission
            if (
                not request.user.is_staff
                and invoice.created_by != request.user
            ):
                raise PermissionDenied

            state_service = InvoiceStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = invoice.state

            # 4. Authorization based on original state
            #
            # Normal users may reset only from the states that
            # are considered ordinary workflow resets.
            #
            # Staff may also reset POSTED invoices.
            if not request.user.is_staff:
                if previous_state != state_service.POSTED:
                    raise PermissionDenied(
                        "You are not allowed to reset this invoice."
                    )

            # 5. State service performs business validation
            result = state_service.transition(
                invoice,
                state_service.DRAFT,
            )

            if not result.get("success"):
                errors = result.get("errors")

                if isinstance(errors, dict):
                    messages = []

                    for field_errors in errors.values():
                        messages.extend(field_errors)

                    raise ValidationError(
                        messages
                        or "This invoice cannot be reset to draft right now."
                    )

                raise ValidationError(
                    errors
                    or "This invoice cannot be reset to draft right now."
                )

            # 6. Accounting reversal
            #
            # A posted AccountMove must never be deleted or edited.
            # It must be reversed with a new AccountMove.
            reversal_move = None

            if invoice_id:

                # Reversing accounting entries is administrative.
                if not request.user.is_staff:
                    raise PermissionDenied(
                        "Administrative permission is required "
                        "to reverse the posted accounting entry."
                    )

                # Prevent duplicate reversal
                if invoice.reversal_of:
                    raise ValidationError(
                        "This invoice already has an accounting reversal."
                    )

                reversal_payload = create_payload(
                    ref=invoice.name,
                    reason="reset",
                    amount=str(invoice.amount_total),
                    source="move",
                    origin_id=invoice.pk,
                    origin_type="invoice",
                )

                reversal_move = reverse_move(
                    reversal_payload,
                    request.user,
                )


                active_deliveries = (
                    StockPicking.objects
                    .select_for_update()
                    .filter(account_move=invoice)
                    .exclude(status=StockPicking.Status.CANCELLED)
                )

                if (
                        request.user.is_staff
                        and previous_state == state_service.POSTED
                ):
                    for delivery in active_deliveries:
                        delivery.cancel()

            # 7. Persist state
            #
            # transition() already changed:
            #
            # invoice.status = DRAFT
            #

            invoice.reversal_of = reversal_move

            update_fields = ["state"]

            if reversal_move:
                update_fields.append("reversal_of")

            invoice.save(update_fields=update_fields)

            reverse_qty_invoiced(invoice)

            # 8. Event
            event = create_event(
                event_type=AccountingEventType.INVOICE_RESET_TO_DRAFT,
                payload={
                    "invoice_id": invoice.pk,
                    "invoice_number": invoice.name,
                    "partner_id": invoice.partner_id,
                    "previous_status": previous_state,
                    "new_status": state_service.DRAFT,
                    "account_move_reversed": bool(
                        reversal_move
                    ),
                    "reversal_move_id": (
                        reversal_move.pk
                        if reversal_move
                        else None
                    ),
                },
                user_id=request.user.pk,
                source=(
                    "htmx"
                    if request.headers.get("HX-Request")
                    else "web"
                ),
            )

            transaction.on_commit(
                lambda: dispatch(event)
            )

    except ValidationError as e:
        if hasattr(e, "messages"):
            message = " ".join(e.messages)
        else:
            message = str(e)

        return htmx_error(
            request,
            message,
            detail_url,
        )

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to reset this invoice.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to reset invoice %s to draft",
            invoice_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Invoice reset to draft successfully.",
        redirect_url=detail_url,
        target="#invoice-display",
    )

def refresh_invoice_view(request, invoice_id):

    invoice = load_account_move(
        invoice_id,
        request
    )

    header_form = MoveForm(
        request.POST or None,
        instance=invoice,
        company=request.company,
    )

    formset = MoveLineFormSet(
        request.POST or None,
        instance=invoice,
        prefix="items",
        form_kwargs={"doc": invoice},
    )

    context = _build_context(
        request=request,
        invoice=invoice,
        header_form=header_form,
        formset=formset,
    )


    if request.headers.get('HX-Request'):
        return render(request, 'accounting/invoice_templates/partials/move_detail_partial.html',context)

    return render(request, 'accounting/invoice_templates/partials/move_detail.html',context)

