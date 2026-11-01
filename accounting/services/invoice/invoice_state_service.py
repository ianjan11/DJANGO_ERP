from core.utils.result import ok, fail
from inventory.models import StockPicking


class InvoiceStateService:
    """
    Controls invoice workflow state and transitions.

    Scope:
    - Customer invoices
    - Customer credit notes
    - Vendor bills
    - Vendor credit notes

    Manual journal entries are handled by AccountMoveStateService.

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
    # =========================================================

    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"

    # =========================================================
    # MOVE TYPE SCOPE
    # =========================================================

    INVOICE_TYPES = (
        "out_invoice",
        "out_refund",
        "in_invoice",
        "in_refund",
        "entry"
    )

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

    def _is_invoice(self, move):
        """True only for invoice/bill/credit-note move types."""
        return move.move_type in self.INVOICE_TYPES

    # =========================================================
    # EDITABILITY
    # =========================================================

    def is_editable(self, move):
        """Only draft invoices are editable."""
        return (
            move.state == self.DRAFT
            and self._is_invoice(move)
        )

    # =========================================================
    # DELETE RULES
    # =========================================================

    def can_delete(self, move):
        """Only draft invoices may be deleted."""
        return (
            move.state == self.DRAFT
            and self._is_invoice(move)
        )

    # =========================================================
    # POSTING VALIDATION
    # =========================================================

    def can_post(self, move):
        """Validate an invoice before posting."""
        errors = {}

        if not self._is_invoice(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not an "
                f"invoice and cannot be posted through the "
                f"invoice workflow."
            ]

        if not move.partner_id:
            errors["partner"] = [
                "Invoice requires a partner."
            ]

        if not move.lines.exists():
            errors["lines"] = [
                "Invoice requires at least one line item."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # PAYMENT VALIDATION
    # =========================================================

    def can_mark_paid(self, move):
        """Validate whether the invoice can be marked paid."""
        errors = {}

        if getattr(move, "amount_residual", 0) > 0:
            errors["payment"] = [
                "Invoice still has an outstanding balance."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # PAYMENT LOCK
    # =========================================================

    def _has_payment_allocations(self, move):
        """
        True when the invoice has payment allocations.

        payment_state is derived from reconciliation state.
        """
        return getattr(
            move,
            "payment_state",
            None,
        ) in (
            "partial",
            "paid",
        )

    # =========================================================
    # INVENTORY LOCK
    # =========================================================

    def _has_completed_inventory(self, move):
        """
        True when the invoice has completed inventory movements.
        """

        pickings_qs = (
            getattr(move, "stock_pickings", None)
            or getattr(move, "pickings", None)
        )

        if not pickings_qs:
            return False

        return pickings_qs.exclude(
            status=StockPicking.Status.CANCELLED
        ).filter(
            status=StockPicking.Status.COMPLETED
        ).exists()

    # =========================================================
    # CANCELLATION VALIDATION
    # =========================================================

    def can_cancel(self, move):
        """
        Validate whether an invoice may be cancelled.

        Draft:
            May be cancelled.

        Posted:
            May be cancelled only when there are no payment
            allocations and no completed inventory movements.

        Cancelled:
            Cannot be cancelled again.
        """

        errors = {}

        if not self._is_invoice(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not an "
                f"invoice and cannot be cancelled here."
            ]

        # -----------------------------------------------------
        # Payment lock
        # -----------------------------------------------------

        if self._has_payment_allocations(move):
            errors["payment"] = [
                "Invoice has payment allocations and cannot "
                "be cancelled. Remove payment allocations first."
            ]

        # -----------------------------------------------------
        # Inventory lock
        # -----------------------------------------------------

        if self._has_completed_inventory(move):
            errors["delivery"] = [
                "Invoice has completed inventory movements and "
                "cannot be cancelled. Process delivered goods "
                "through returns instead."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # RESET TO DRAFT VALIDATION
    # =========================================================

    def can_reset_to_draft(self, move):
        """
        Validate whether an invoice can be reset to draft.

        Posted invoice may be reset only when:
        - it is an invoice/bill/credit note
        - no payment allocations exist
        - no completed inventory movements exist

        The actual reversal/removal of accounting records is
        handled by the reset operation, not this service.
        """

        errors = {}

        if not self._is_invoice(move):
            errors["move_type"] = [
                f"Move with type '{move.move_type}' is not an "
                f"invoice and cannot be reset to draft here."
            ]

        # -----------------------------------------------------
        # Payment lock
        # -----------------------------------------------------

        if self._has_payment_allocations(move):
            errors["payment"] = [
                "Cannot reset to draft while payment allocations "
                "exist. Unreconcile all payments first."
            ]

        # -----------------------------------------------------
        # Inventory lock
        # -----------------------------------------------------

        if self._has_completed_inventory(move):
            errors["delivery"] = [
                "Cannot reset to draft while completed inventory "
                "movements exist. Process delivered goods through "
                "returns instead."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # MAIN TRANSITION METHOD
    # =========================================================

    def transition(self, move, new_state):
        """
        Validate and apply an invoice state transition.

        This method only mutates move.state.
        The caller is responsible for saving the invoice
        and performing side effects such as accounting
        posting, reversal, or inventory operations.
        """

        current_state = move.state

        # -----------------------------------------------------
        # Already in requested state
        # -----------------------------------------------------

        if current_state == new_state:
            return fail(
                errors={
                    "state": [
                        f"Invoice is already {current_state}."
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
            validation = self.can_post(move)

        elif new_state == self.CANCELLED:
            validation = self.can_cancel(move)

        elif new_state == self.DRAFT:
            validation = self.can_reset_to_draft(move)

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

        move.state = new_state

        return ok(
            success=True,
            changed=True,
            old_state=old_state,
            new_state=new_state,
        )

    # =========================================================
    # STATE FLAGS
    # =========================================================

    def get_flags(self, move):
        """
        Return workflow flags for frontend/UI logic.

        These flags describe the basic state-level possibility.
        Full business validation is still enforced by transition()
        and the corresponding backend operation.

        Non-invoice move types will show all invoice workflow
        actions as False.
        """

        is_invoice = self._is_invoice(move)

        return {
            "editable": self.is_editable(move),

            "can_delete": self.can_delete(move),

            "can_post": (
                is_invoice
                and move.state == self.DRAFT
            ),

            "can_cancel": (
                is_invoice
                and move.state in (
                    self.DRAFT,
                    self.POSTED,
                )
            ),

            "can_reset_to_draft": (
                is_invoice
                and move.state == self.POSTED
            ),

            "locked": (
                move.state in (
                    self.POSTED,
                    self.CANCELLED,
                )
            ),
        }