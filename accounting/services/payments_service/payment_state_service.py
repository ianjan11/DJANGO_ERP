from decimal import Decimal
from core.utils.result import ok, fail


from decimal import Decimal

from core.utils.result import ok, fail


class PaymentStateService:
    """
    Controls payment workflow state and transitions.

    Responsibilities:
    - state transitions
    - workflow locks
    - edit permissions
    - posting guards
    - cancellation rules
    - reset-to-draft rules

    Does NOT:
    - update payment rows
    - create/reverse AccountMoves
    - create payment allocations
    - perform reconciliation
    - calculate payment amounts
    """

    # =========================================================
    # WORKFLOW STATES
    # =========================================================

    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"

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

    # =========================================================
    # EDITABILITY
    # =========================================================

    def is_editable(self, payment):
        """Only draft payments are editable."""
        return payment.state == self.DRAFT

    # =========================================================
    # DELETE RULES
    # =========================================================

    def can_delete(self, payment):
        """Only draft payments may be deleted."""
        return payment.state == self.DRAFT

    # =========================================================
    # APPLY PREPAYMENT RULES
    # =========================================================
    def can_apply_prepayment(self, payment):
        """Only posted pre-payments that haven't already been swapped may be applied."""
        if not (payment.state == self.POSTED and payment.is_prepayment):
            return False

        from accounting.models import AccountMove
        already_swapped = AccountMove.objects.filter(
            origin_type="payment",
            origin_id=payment.id,
            is_prepayment_swap=True,
        ).exists()

        return not already_swapped

    # =========================================================
    # POSTING VALIDATION
    # =========================================================

    def can_post(self, payment):
        """Validate a payment before posting."""
        errors = {}

        # -----------------------------------------------------
        # Company
        # -----------------------------------------------------
        if not payment.company_id:
            errors["company"] = [
                "Payment requires a company."
            ]

        # -----------------------------------------------------
        # Payment direction & counterparties
        # -----------------------------------------------------
        if payment.payment_type in ("INCOMING", "OUTGOING"):
            if not payment.partner_id:
                errors["partner"] = [
                    "Incoming and outgoing payments require a partner."
                ]
            if not payment.partner_type:
                errors["partner_type"] = [
                    "Payment requires a partner type."
                ]
            if payment.destination_journal_id:
                errors["destination_journal"] = [
                    "Destination journal is only valid for transfer payments."
                ]

        elif payment.payment_type == "TRANSFER":
            if payment.partner_id:
                errors["partner"] = [
                    "Internal transfers must not have a partner."
                ]
            if not payment.destination_journal_id:
                errors["destination_journal"] = [
                    "Internal transfers require a destination journal."
                ]
            elif payment.journal_id and payment.destination_journal_id == payment.journal_id:
                errors["destination_journal"] = [
                    "Source and destination journals must be different."
                ]

        # -----------------------------------------------------
        # Amount
        # -----------------------------------------------------
        if payment.amount is None:
            errors["amount"] = [
                "Payment amount is required."
            ]
        elif payment.amount <= Decimal("0"):
            errors["amount"] = [
                "Payment amount must be greater than zero."
            ]

        # -----------------------------------------------------
        # Currency & Journal
        # -----------------------------------------------------
        if not payment.currency_id:
            errors["currency"] = [
                "Payment requires a currency."
            ]

        if not payment.journal_id:
            errors["journal"] = [
                "Payment requires a journal."
            ]

        # -----------------------------------------------------
        # Existing AccountMove guard
        # -----------------------------------------------------
        if payment.account_move_id:
            errors["account_move"] = [
                "Payment already has an accounting move."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # CANCELLATION VALIDATION
    # =========================================================

    def can_cancel(self, payment):
        """
        Validate whether a payment may be cancelled.

        Important:

        DRAFT:
            Can be cancelled normally.

        POSTED:
            May be cancelled administratively.
            The cancellation operation must reverse the
            associated AccountMove.

        RECONCILED / PARTIALLY RECONCILED:
            Cannot be cancelled until payment allocations
            have been removed.
        """

        errors = {}

        # -----------------------------------------------------
        # Reconciliation lock
        # -----------------------------------------------------

        if getattr(payment, "payment_state", None) in (
            "partial",
            "paid",
        ):
            errors["payment"] = [
                "Payment has reconciliation allocations and cannot "
                "be cancelled. Remove the allocations first."
            ]

        # -----------------------------------------------------
        # AccountMove guard
        # -----------------------------------------------------

        if (
            payment.state == self.POSTED
            and not payment.account_move_id
        ):
            errors["account_move"] = [
                "Posted payment has no associated accounting move."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # RESET TO DRAFT VALIDATION
    # =========================================================

    def can_reset_to_draft(self, payment):
        """
        Validate whether a payment can be reset to draft.

        Posted payments may be reset only when:
        - no payment allocations exist

        The actual reversal/removal of accounting records is
        handled by the reset operation, not this service.
        """

        errors = {}

        # -----------------------------------------------------
        # Reconciliation lock
        # -----------------------------------------------------

        if getattr(payment, "payment_state", None) in (
            "partial",
            "paid",
        ):
            errors["payment"] = [
                "Payment has reconciliation allocations and cannot "
                "be reset to draft."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # MAIN TRANSITION METHOD
    # =========================================================

    def transition(self, payment, new_state):
        """
        Validate and apply a payment state transition.

        This method only mutates payment.state.
        The caller is responsible for saving the payment
        and performing side effects such as accounting
        reversal or reconciliation cleanup.
        """

        current_state = payment.state

        # -----------------------------------------------------
        # Already in requested state
        # -----------------------------------------------------

        if current_state == new_state:
            return fail(
                errors={
                    "state": [
                        f"Payment is already {current_state}."
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
            validation = self.can_post(payment)

        elif new_state == self.CANCELLED:
            validation = self.can_cancel(payment)

        elif new_state == self.DRAFT:
            validation = self.can_reset_to_draft(payment)

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

        payment.state = new_state

        return ok(
            success=True,
            changed=True,
            old_state=old_state,
            new_state=new_state,
        )

    # =========================================================
    # STATE FLAGS
    # =========================================================

    def get_flags(self, payment):
        """
        Return workflow flags for frontend/UI logic.

        Note:
        can_cancel here only describes the basic state-level
        possibility. User permissions and business validation
        should still be enforced by the backend operation.
        """

        return {
            "editable": self.is_editable(payment),

            "can_delete": self.can_delete(payment),

            "can_post": (
                payment.state == self.DRAFT
            ),

            "can_cancel": (
                payment.state in (
                    self.DRAFT,
                    self.POSTED,
                )
            ),

            "can_reset_to_draft": (
                payment.state == self.POSTED
            ),

            "locked": (
                payment.state in (
                    self.POSTED,
                    self.CANCELLED,
                )
            ),
        }