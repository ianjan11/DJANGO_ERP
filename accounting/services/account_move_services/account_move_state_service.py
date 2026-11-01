from django.db.models import Sum

from core.utils.result import ok, fail


class AccountMoveStateService:
    """
    Controls invoice workflow state and transitions.

    Scope: manual journal entries only (move_type == "entry").
    Invoices, bills, and other auto-generated move types are
    managed by their own workflow services.

    Responsibilities:
    - state transitions
    - workflow locks
    - edit permissions
    - posting guards
    - cancellation rules
    - reset-to-draft rules

    Does NOT:
    - update invoice rows
    - calculate totals
    - create/reverse AccountMoves
    - cancel deliveries
    - render templates
    """

    # =========================================================
    # WORKFLOW STATES
    # (lowercase values to match AccountMove.STATE_CHOICES)
    # =========================================================

    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"

    # =========================================================
    # MOVE TYPE SCOPE
    # =========================================================

    ENTRY_MOVE_TYPE = "entry"

    # =========================================================
    # ALLOWED TRANSITIONS
    # =========================================================

    ALLOWED_TRANSITIONS = {
        DRAFT: [POSTED, CANCELLED],
        POSTED: [DRAFT, CANCELLED],
        CANCELLED: [],
    }

    # =========================================================
    # STATE CHECKS
    # =========================================================

    def can_transition(self, current_state, new_state):
        """Check whether a state transition is allowed."""
        return new_state in self.ALLOWED_TRANSITIONS.get(
            current_state,
            []
        )

    def _is_manual_entry(self, move):
        """True only for manual journal entries."""
        return move.move_type == self.ENTRY_MOVE_TYPE

    # =========================================================
    # EDITABILITY
    # =========================================================

    def is_editable(self, move):
        """Only draft manual entries are editable."""
        return move.state == self.DRAFT and self._is_manual_entry(move)

    # =========================================================
    # DELETE RULES
    # =========================================================

    def can_delete(self, move):
        """Only draft manual entries may be deleted."""
        return move.state == self.DRAFT and self._is_manual_entry(move)

    # =========================================================
    # POSTING VALIDATION
    # =========================================================

    def can_post(self, move):
        """Validate a move before posting."""
        errors = {}

        if not self._is_manual_entry(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not a manual "
                f"journal entry and cannot be posted manually."
            ]

        if not move.partner_id:
            errors["partner"] = [
                "Move requires a partner."
            ]

        if not move.lines.exists():
            errors["lines"] = [
                "Move requires at least one line item."
            ]

        lines = move.lines.all()

        for line in lines:
            if line.debit < 0 or line.credit < 0:
                errors.setdefault("Incorrect_lines", []).append(
                    "Debit/Credit must be positive."
                )

            if line.debit > 0 and line.credit > 0:
                errors.setdefault("Incorrect_lines", []).append(
                    "Line cannot have both debit and credit."
                )

        total_debit = lines.aggregate(total=Sum("debit"))["total"] or 0
        total_credit = lines.aggregate(total=Sum("credit"))["total"] or 0

        if total_debit != total_credit:
            errors["unbalanced_journal"] = [
                "Total debit must be equal to total credit."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # CANCELLATION VALIDATION
    # =========================================================

    def can_cancel(self, move):
        """
        Validate whether a move may be cancelled.

        Important:

        DRAFT:
            Can be cancelled normally.

        POSTED:
            May be cancelled administratively.
            The cancellation operation must reverse the
            associated AccountMove.

        AMOUNT RESIDUAL:
            Cannot be cancelled until residuals
            have been removed/ residual must equal move amount.

        LINES:
        all lines must be unreconciled
        """
        errors = {}

        if not self._is_manual_entry(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not a manual "
                f"journal entry and cannot be cancelled here."
            ]

        if move.state == self.POSTED:
            if move.amount_residual != move.amount_total:
                errors["amount_residual"] = [
                    "Move has payment allocations; amount residual "
                    "must equal the move total before it can be "
                    "cancelled."
                ]

            if move.lines.filter(reconciled=True).exists():
                errors["lines"] = [
                    "All lines must be unreconciled before the move "
                    "can be cancelled."
                ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # RESET TO DRAFT VALIDATION
    # =========================================================

    def can_reset_to_draft(self, move):
        """
        Validate whether a move can be reset to draft.

        Posted move may be reset only when:
        - it is a manual journal entry
        - no payment allocations exist
        - no physical delivery has occurred

        The actual reversal/removal of accounting records is
        handled by the reset operation, not this service.
        """
        errors = {}

        if not self._is_manual_entry(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not a manual "
                f"journal entry and cannot be reset to draft here."
            ]

        if move.amount_residual != move.amount_total:
            errors["amount_residual"] = [
                "Cannot reset to draft while payment allocations "
                "exist. Unreconcile all payments first."
            ]

        if move.lines.filter(reconciled=True).exists():
            errors["lines"] = [
                "Cannot reset to draft while reconciled lines exist."
            ]

        # No delivery/fulfillment model is present in the AccountMove
        # model shown, so a physical-delivery check can't be wired in
        # here yet. If deliveries hang off `origin_type`/`origin_id`
        # or a related model, tell me the relation and I'll add the
        # check.

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # MAIN TRANSITION METHOD
    # =========================================================

    def transition(self, invoice, new_state):
        """
        Validate and apply an invoice state transition.

        This method only mutates invoice.state.
        The caller is responsible for saving the invoice
        and performing side effects such as accounting
        reversal or delivery cancellation.
        """

        current_state = invoice.state

        # -----------------------------------------------------
        # Already in requested state
        # -----------------------------------------------------

        if current_state == new_state:
            return fail(
                errors={
                    "state": [
                        f"Journal is already {current_state}."
                    ]
                },
                success=False,
                changed=False,
            )

        # -----------------------------------------------------
        # Transition not allowed
        # -----------------------------------------------------

        if not self.can_transition(
            current_state,
            new_state,
        ):
            return fail(
                errors={
                    "state": [
                        f"Cannot transition from "
                        f"'{current_state}' to "
                        f"'{new_state}'."
                    ]
                },
                success=False,
                changed=False,
            )

        # -----------------------------------------------------
        # State-specific validation
        # -----------------------------------------------------

        validation = ok()

        if new_state == self.POSTED:
            validation = self.can_post(invoice)

        elif new_state == self.CANCELLED:
            validation = self.can_cancel(invoice)

        elif new_state == self.DRAFT:
            validation = self.can_reset_to_draft(invoice)

        # -----------------------------------------------------
        # Validation failed
        # -----------------------------------------------------

        if validation.get("errors"):
            return fail(
                errors=validation["errors"],
                success=False,
                changed=False,
            )

        # -----------------------------------------------------
        # Apply transition
        # -----------------------------------------------------

        old_state = current_state

        invoice.state = new_state

        return ok(
            success=True,
            changed=True,
            old_state=old_state,
            new_state=new_state,
        )

    # =========================================================
    # STATE FLAGS
    # =========================================================

    def get_flags(self, invoice):
        """
        Return workflow flags for frontend/UI logic.

        Note:
        can_cancel here only describes the basic state-level
        possibility. User permissions and business validation
        should still be enforced by the backend operation.

        Flags assume `invoice` is a manual journal entry
        (move_type == "entry"); non-entry moves will show
        can_post/can_cancel/can_reset_to_draft as False.
        """

        is_entry = self._is_manual_entry(invoice)

        return {
            "editable": self.is_editable(invoice),

            "can_delete": self.can_delete(invoice),

            "can_post": (
                is_entry and invoice.state == self.DRAFT
            ),

            "can_cancel": (
                is_entry and invoice.state in (
                    self.DRAFT,
                    self.POSTED,
                )
            ),

            "can_reset_to_draft": (
                is_entry and invoice.state == self.POSTED
            ),

            "locked": (
                invoice.state in (
                    self.POSTED,
                    self.CANCELLED,
                )
            ),
        }