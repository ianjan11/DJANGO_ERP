from datetime import date
from decimal import Decimal
from typing import Any
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from purchases.models import PurchaseOrder
from sales.models import SalesOrder

REVERSAL_TYPE_MAP = {
    "out_invoice": "out_refund",
    "in_invoice":  "in_refund",
    "out_refund":  "out_invoice",
    "in_refund":   "in_invoice",
    "payment":     "payment",
}


def create_payload(
    ref: object,
    amount: object,
    source: object,
    reason: object,
    origin_type: object,
    origin_id: object,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "amount": amount,
        "source": source,
        "reason": reason,
        "origin_type": origin_type,
        "origin_id": origin_id,
    }


def resolve_source(payload):

    from accounting.models import Payment,AccountMove

    source_map = {
        "move": AccountMove,
        "payment": Payment,
    }

    model = source_map.get(payload["source"])
    if not model:
        raise ValidationError(f"Unknown source type: {payload['source']}")

    try:
        return model.objects.get(pk=payload["origin_id"])
    except model.DoesNotExist:
        raise ValidationError(
            f"No {payload['source']} found for id '{payload['origin_id']}'."
        )

def reverse_move(payload, user):

    from accounting.models import  AccountMove, AccountMoveLine
    from accounting.services.Period_validators import PeriodValidator

    obj  = resolve_source(payload)

    if not obj :
        return None

    cancel_date = date.today()
    PeriodValidator.validate_period(obj.company, cancel_date)

    journal = obj.journal
    if not journal:
        raise ValidationError("Journal not found.")

    if obj.move_type not in REVERSAL_TYPE_MAP:
        raise ValidationError(f"Cannot reverse move type '{obj.move_type}'.")


    unreconcile_move(obj)

    move_name = journal.get_next_number()

    reversal_move = AccountMove.objects.create(
        move_type        = REVERSAL_TYPE_MAP[obj.move_type],
        reversal_of      = obj,
        reversal_reason  = f"{payload['reason']}",
        issue_date             = cancel_date,
        due_date         = cancel_date,
        partner          = obj.partner,
        currency         = obj.currency,
        company          = obj.company,
        journal          = journal,
        ref              = f"REV: {payload['ref']}",
        name             = f"REV: {move_name}",
        amount_untaxed   = obj.amount_untaxed,
        amount_tax       = obj.amount_tax,
        amount_total     = obj.amount_total,
        amount_residual  = Decimal("0"),
        created_by       = user,
        origin_type = f"{payload['origin_type']}",
        origin_id = f"{payload['origin_id']}",

    )

    reversal_lines = []

    allowed_lines = obj.lines.all().exclude(line_type = AccountMoveLine.LineType.PRODUCT)

    for line in allowed_lines:
        reversal_lines.append(AccountMoveLine(
            move             = reversal_move,
            account          = line.account,
            partner          = line.partner,
            debit            = line.credit,
            credit           = line.debit,
            original_amount  = -(line.original_amount or Decimal("0")),
            foreign_currency=line.foreign_currency,
            date             = cancel_date,
            memo             = f"REV: {line.memo}",
            line_type =      line.line_type,
            source_line_id = line.id,
            source_line = line
        ))

    for line in reversal_lines:
        line.full_clean()

    AccountMoveLine.objects.bulk_create(reversal_lines)
    reversal_move.post(user)

    obj.amount_residual = Decimal("0")
    obj.save(update_fields=["amount_residual"])

    return reversal_move

@transaction.atomic
def unreconcile_move(move):
    from accounting.models import PartialReconcile, AccountMoveLine, AccountMove
    from accounting.services.account_move_services.invoice_account_move_services import _model_has_field
    from accounting.services.account_move_services.shared.account_utils import round2

    """
    Reverse every PartialReconcile involving any line on `move`,
    restoring residual/applied state on the counterpart entries and
    their moves, then deleting the reconciliation rows.

    Works purely off the persisted PartialReconcile ledger — there is
    no allocation context available here, unlike at creation time.
    Handles both GRNI/GDNI reconciliations and payment/invoice
    reconciliations transparently, since PartialReconcile doesn't
    distinguish the two.
    """
    move_lines = list(move.lines.select_for_update())
    move_line_ids = {l.id for l in move_lines}

    reconciliations = list(
        PartialReconcile.objects
        .filter(Q(debit_line_id__in=move_line_ids) | Q(credit_line_id__in=move_line_ids))
        .select_for_update()
    )

    if not reconciliations:
        return

    # Resolve every distinct counterpart line/move ONCE and lock them,
    # so multiple reconciliations against the same entry or move
    # accumulate correctly instead of clobbering each other on save.
    entry_ids = {
        (r.credit_line_id if r.debit_line_id in move_line_ids else r.debit_line_id)
        for r in reconciliations
    }
    entries = {
        e.id: e
        for e in AccountMoveLine.objects.filter(id__in=entry_ids).select_for_update()
    }
    entry_moves = {
        m.id: m
        for m in AccountMove.objects
        .filter(id__in={e.move_id for e in entries.values()})
        .select_for_update()
    }

    for recon in reconciliations:
        entry_id = (
            recon.credit_line_id
            if recon.debit_line_id in move_line_ids
            else recon.debit_line_id
        )
        entry = entries[entry_id]
        entry_move = entry_moves[entry.move_id]
        applied = recon.amount

        entry_move.amount_residual = round2(
            Decimal(str(entry_move.amount_residual or "0.00")) + applied
        )
        entry_move.reconciled = False

        if _model_has_field(entry, "amount_applied"):
            entry.amount_applied = max(
                Decimal("0.00"),
                round2(Decimal(str(entry.amount_applied or "0.00")) - applied),
            )
        entry.reconciled = False

    for entry in entries.values():
        update_fields = ["reconciled"]
        if _model_has_field(entry, "amount_applied"):
            update_fields.append("amount_applied")
        entry.save(update_fields=update_fields)

    for entry_move in entry_moves.values():
        entry_move.save(update_fields=["amount_residual", "reconciled"])

    PartialReconcile.objects.filter(
        id__in=[r.id for r in reconciliations]
    ).delete()


@transaction.atomic
def reverse_qty_invoiced(invoice):
    lines = list(
        invoice.lines
        .select_for_update()
    )

    for line in lines:
        instance = line.source_line

        if instance is None:
            continue


        previous_invoiced = instance.qty_invoiced or 0
        reversal_qty = line.quantity or 0

        if reversal_qty <= 0:
            raise ValidationError(
                "Reversal quantity must be greater than zero."
            )

        if reversal_qty > previous_invoiced:
            raise ValidationError(
                "Cannot reverse more than the currently invoiced quantity."
            )

        new_invoiced = previous_invoiced - reversal_qty

        instance.qty_invoiced = new_invoiced

        instance.save(
            update_fields=["qty_invoiced"]
        )
