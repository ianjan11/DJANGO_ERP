import json
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, Http404
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounting.events.accounting_events import create_event
from accounting.events.types import AccountingEventType
from accounting.forms import ReconcilePaymentForm
from accounting.forms.account_move_form import MoveForm, MoveLineFormSet
from accounting.services import reverse_move, create_payload
from accounting.services.account_move_services.account_move_loader import load_account_move
from accounting.services.account_move_services.account_move_state_service import AccountMoveStateService
from accounting.services.account_move_services.get_default_journal import get_default_journal
from accounting.services.account_move_services.finalize_manual_journal import \
    finalize_manual_journal_post
from accounting.utils.get_account_move_source import get_source
from core.events import dispatch
import logging

from core.services.document_service.core.payload_builder import build_payload
from core.services.document_service.document_service import DocumentService
from core.services.document_service.presentation.htmx_swap_service import UIResponseService
from core.utils import htmx_error, htmx_success

logger = logging.getLogger("sales.invoice")

from django.db.models import Q
from accounting.models import AccountMove,  PartialReconcile

CUSTOMER_MOVE_TYPES = ["out_invoice", "out_refund"]
VENDOR_MOVE_TYPES = ["in_invoice", "in_refund"]

def _get_applicable_move_types(move_type: str) -> list[str]:
    """Return matching document move types based on current move orientation."""
    if move_type in CUSTOMER_MOVE_TYPES:
        return CUSTOMER_MOVE_TYPES
    if move_type in VENDOR_MOVE_TYPES:
        return VENDOR_MOVE_TYPES
    return CUSTOMER_MOVE_TYPES + VENDOR_MOVE_TYPES

def _build_context(request, move, header_form, formset):
    lines = list(move.lines.select_related("account").all())

    # 1. Existing Reconciliations linked to this move's lines
    partial_reconcile = PartialReconcile.objects.filter(
        Q(debit_line__in=lines) | Q(credit_line__in=lines)
    ).select_related(
        "debit_line__move",
        "credit_line__move",
        "debit_line__account",
        "credit_line__account",
    )

    form = ReconcilePaymentForm()

    # 5. Build active applied reconciliation records for display
    reconciled_moves_data = []

    for rec in partial_reconcile:
        # Determine which side of the partial reconcile belongs to the counterpart move
        if rec.debit_line in lines:
            target_line = rec.credit_line
        else:
            target_line = rec.debit_line

        reconciled_move = target_line.move

        # Filter out self-reconciliations or internal swap moves
        if reconciled_move == move:
            continue

        reconciled_moves_data.append({
            "partial_reconcile_id": rec.id,
            "move": reconciled_move,
            "reference": reconciled_move.ref or reconciled_move.name,
            "source": get_source(reconciled_move),
            "date": reconciled_move.issue_date,
            "amount_applied": rec.amount,
            "amount_residual": reconciled_move.amount_residual,
            "amount_total": reconciled_move.amount_total,
            "currency": reconciled_move.currency,
        })

    return {
        "form": form,
        "reconciled_invoices": reconciled_moves_data,
        "partner_type": getattr(move.partner, "partner_type", None),
        "move": move,
        "header_form": header_form,
        "formset": formset,
        "lines": lines,
        "partial_reconcile": partial_reconcile,
    }

@login_required
def journal_entries(request):

    today = timezone.now().date()

    qs = AccountMove.objects.filter(
        company=request.company,
    )

    search_move = request.GET.get('search_move')
    if search_move:
        qs = qs.filter(
            Q(ref__icontains=search_move) |
            Q(name__icontains=search_move),
        )

    move_status = request.GET.get('move_status')
    if move_status:
        qs = qs.filter(status=move_status)

    preset = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        qs = qs.filter(date=target_date)
    elif preset == 'Today':
        qs = qs.filter(date=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        qs = qs.filter(date__gte=week_start, date__lte=week_end)
    elif preset == 'ThisMonth':
        qs = qs.filter(date__year=today.year, date__month=today.month)
    elif preset == 'ThisYear':
        qs = qs.filter(date__year=today.year)

    qs = qs.select_related('company').order_by('-created_at')

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'search_move': search_move or '',
        'move_status': move_status or '',
        'preset': preset or '',
        'target_date': target_date or '',
    }

    template = (
        'accounting/journals/partials/journals_table.html'
        if request.headers.get("HX-Request")
        else 'accounting/journals/journals_list.html'
    )

    return render(request, template, context)

@login_required
def journal_create_or_detail(request, move_id=None):
    # ─────────────────────────────────────
    # CREATE FLOW
    # ─────────────────────────────────────
    if not move_id:
        try:
            with transaction.atomic():

                default_journal = get_default_journal(request.company)


                move = AccountMove.objects.create(
                    move_type=AccountMove.MoveType.ENTRY,
                    issue_date=timezone.now().date(),
                    company=request.company,
                    currency=request.company.currency,
                    created_by=request.user,
                    journal=default_journal,
                )

                event = create_event(
                    event_type=AccountingEventType.ACCOUNT_MOVE_CREATED,
                    user_id=request.user.id,
                    source="htmx" if request.headers.get('HX-Request') else "web",
                    payload={
                        "move": move
                    }
                )

                transaction.on_commit(lambda: dispatch(event))

        except Exception as e:
            logger.exception("Failed to create account move: %s", e)
            messages.error(request, "Something went wrong. Please try again.")
            return htmx_error(request,"Failed to initialize draft document. Please try again.")

        return redirect("accounting:journal_detail", move_id=move.id)

    # ─────────────────────────────────────
    # DETAIL / EDIT FLOW
    # ─────────────────────────────────────
    move = load_account_move(move_id, request)

    header_form = MoveForm(
        request.POST or None,
        company=request.company,
        instance=move,
    )

    formset = MoveLineFormSet(
        request.POST or None,
        instance=move,
        form_kwargs={"doc": move},
        prefix="items",
    )

    context = _build_context(
        request=request,
        move=move,
        header_form=header_form,
        formset=formset,
    )

    template = (
        'accounting/journals/partials/journal_detail_partial.html'
        if request.headers.get("HX-Request")
        else 'accounting/journals/journal_detail.html'
    )

    return render(request, template, context)

@login_required
def journal_item_row(request, move_id):
    move = load_account_move(move_id, request, for_update=False)


    partner_id = move.partner_id

    if not partner_id:
        if request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            response["HX-Trigger"] = json.dumps({
                "showNotification": {
                    "message": "Please select a partner first.",
                    "level": "error"
                }
            })
            return response

        messages.error(request, "Please select a partner first.")
        return redirect("accounting:journal_detail", move_id=move_id)

    prefix = request.GET.get('prefix', 'items')
    total_forms = int(request.GET.get('total_forms', 0))

    # Initialize formset with form_kwargs so accounts stay scoped to company/move
    formset = MoveLineFormSet(
        instance=move,
        prefix=prefix,
        form_kwargs={"doc": move},
    )

    form = formset.empty_form

    form.prefix = f"{prefix}-{total_forms}"

    html = render_to_string(
        'accounting/journals/partials/journal_item_row.html',
        {
            'form': form,
            'move': move,
            'invoice': move,  # Compatibility alias if template references invoice
        },
        request=request,
    )

    return HttpResponse(html)

@login_required
@require_POST
def journal_update(request):

    move_id = request.POST.get("move_id")

    if not move_id:
        return HttpResponseBadRequest("Missing move_id")

    with transaction.atomic():
        move = load_account_move(move_id, request, for_update=True)

        payload, dropped_unsaved_rows = build_payload(request.POST, doc_type="entry")



        # 2. HAND OFF TO ORCHESTRATOR
        try:
            context = DocumentService().apply_state(
                doc_instance=move,
                payload=payload,
                dropped_unsaved_rows=dropped_unsaved_rows,
                request=request,
                user=request.user,
            )
        except Exception:
            logger.exception("apply_state failed for move_id=%s", move_id)
            raise

    return UIResponseService().render(request=request, payload=context)

def journal_totals(request, move_id):
    move = load_account_move(move_id, request)
    return render(request, 'accounting/journals/partials/journal_totals.html', {'move': move})

@require_POST
@login_required
def post_journal_view(request, move_id):

    detail_url = reverse("accounting:journal_detail", kwargs={"move_id": move_id})

    try:
        with transaction.atomic():

            move = load_account_move(move_id, request, for_update=True)

            if not move.has_items():
                return htmx_error(request, "Journal has no items.", detail_url)

            state_service = AccountMoveStateService()

            result = state_service.transition(move, state_service.POSTED)

            if not result.get("success"):
                raise ValidationError(
                    result.get("errors") or "This journal cannot be posted right now."
                )

            finalize_manual_journal_post(move, request.user)

            event = create_event(
                event_type=AccountingEventType.ACCOUNT_MOVE_POSTED,
                payload={
                    "move_id": move.pk,
                    "name": move.name,
                    "partner_id": move.partner_id,
                    "amount": str(move.amount_total),
                },
                user_id=request.user.pk,
                source="htmx" if request.headers.get('HX-Request') else "web",
            )

            transaction.on_commit(lambda: dispatch(event))

    except ValidationError as e:
        message = " ".join(e.messages) if hasattr(e, "messages") else str(e)
        return htmx_error(request, message, detail_url)
    except (Http404, PermissionDenied):
        raise
    except Exception:
        logger.exception("Failed to post move %s", move_id)
        return htmx_error(request, "Something went wrong. Please try again.", detail_url)

    return htmx_success(
        request,
        message="Move Posted Successfully",
        redirect_url=detail_url,
        target="#accounting-display",
    )

@require_POST
@login_required
def cancel_journal_view(request, move_id):
    detail_url = reverse("accounting:journal_detail", kwargs={"move_id": move_id})

    try:
        with transaction.atomic():

            move = load_account_move(move_id, request, for_update=True)

            # 2. Basic document permission
            if (
                not request.user.is_staff
                and move.created_by != request.user
            ):
                raise PermissionDenied

            state_service = AccountMoveStateService()

            # 3. Capture original state BEFORE transition()
            previous_state = move.state

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

            result = state_service.transition(move, state_service.CANCELLED)

            if not result.get("success"):
                errors = result.get("errors")

                if isinstance(errors, dict):
                    messages = []

                    for field_errors in errors.values():
                        messages.extend(field_errors)

                    raise ValidationError(
                        messages
                        or "This move cannot be cancelled right now."
                    )

                raise ValidationError(
                    errors
                    or "This move cannot be cancelled right now."
                )

            # 6. Administrative accounting reversal
            #
            # A GL reversal is only needed when the move was actually
            # POSTED — draft moves never had accounting entries to
            # reverse. Gate on `previous_state`, not on `move` being
            # truthy (that was always true and silently blocked every
            # non-staff cancellation, including valid draft ones).
            reversal_move = None

            if previous_state == state_service.POSTED:

                if not request.user.is_staff:
                    raise PermissionDenied(
                        "Administrative permission is required "
                        "to reverse the posted accounting entry."
                    )

                # Never create a second reversal
                if move.reversal_move_id:
                    raise ValidationError(
                        "This invoice already has an accounting reversal."
                    )

                reversal_payload = create_payload(
                    ref=move.name,
                    reason="cancelled",
                    amount=str(move.amount_total),
                    source="move",
                    origin_id=move.pk,
                    origin_type="move",
                )

                reversal_move = reverse_move(
                    reversal_payload,
                    request.user,
                )

                move.reversal_move = reversal_move

            # 7. Persist move state
            update_fields = ["state"]

            if reversal_move:
                update_fields.append("reversal_move")

            move.save(update_fields=update_fields)

            # 8. Event
            event = create_event(
                event_type=AccountingEventType.ACCOUNT_MOVE_CANCELLED,
                payload={
                    "move_id": move.pk,
                    "move_name": move.name,
                    "partner_id": move.partner_id,
                    "previous_status": previous_state,
                    "new_status": state_service.CANCELLED,
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
        message = " ".join(e.messages) if hasattr(e, "messages") else str(e)

        return htmx_error(
            request,
            message,
            detail_url,
        )

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to cancel this journal.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to cancel journal %s",
            move_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Journal cancelled successfully.",
        redirect_url=detail_url,
        target="#accounting-display",
    )

@require_POST
@login_required
def delete_journal_view(request, move_id):
    detail_url = reverse("accounting:journal_detail", kwargs={"move_id": move_id})
    # NOTE: adjust this to your actual "list" url name — the move
    # won't exist anymore after deletion, so redirecting back to
    # detail_url would 404.
    list_url = reverse("accounting:journal_entries")

    try:
        with transaction.atomic():

            move = load_account_move(move_id, request, for_update=True)

            # 2. Basic document permission
            if (
                not request.user.is_staff
                and move.created_by != request.user
            ):
                raise PermissionDenied

            state_service = AccountMoveStateService()

            # 3. State service performs ALL business validation.
            # can_delete is a plain boolean (only DRAFT manual
            # entries are deletable) rather than the ok()/fail()
            # dict used by can_post/can_cancel.
            if not state_service.can_delete(move):
                raise ValidationError(
                    "This move cannot be deleted right now."
                )

            move_pk = move.pk
            move_name = move.name
            partner_id = move.partner_id

            # 4. Delete
            move.delete()

            # 5. Event
            event = create_event(
                event_type=AccountingEventType.ACCOUNT_MOVE_DELETED,
                payload={
                    "move_id": move_pk,
                    "move_name": move_name,
                    "partner_id": partner_id,
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
        message = " ".join(e.messages) if hasattr(e, "messages") else str(e)

        return htmx_error(
            request,
            message,
            detail_url,
        )

    except PermissionDenied:
        return htmx_error(
            request,
            "You do not have permission to delete this journal.",
            detail_url,
        )

    except Http404:
        raise

    except Exception:
        logger.exception(
            "Failed to delete journal %s",
            move_id,
        )

        return htmx_error(
            request,
            "Something went wrong. Please try again.",
            detail_url,
        )

    return htmx_success(
        request,
        message="Journal deleted successfully.",
        redirect_url=list_url,
        target="#accounting-display",
    )



