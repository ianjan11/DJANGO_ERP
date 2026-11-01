from core.utils.result import ok, fail
from inventory.models import StockPicking, stock_picking


class SalesOrdersStateService:
    """
    Controls Sales Order workflow state and transitions.

    Responsibilities:
    - state transitions
    - workflow locks
    - edit permissions
    - confirmation guards
    - cancellation rules
    - reset-to-draft rules

    Does NOT:
    - save the order
    - update order lines
    - calculate totals
    - validate stock availability
    - cancel deliveries
    - create/reverse accounting moves
    - render templates
    """

    # =========================================================
    # WORKFLOW STATES
    # =========================================================

    STATUS = (
        ("DRAFT", "Quotation"),
        ("SENT", "Quotation Sent"),
        ("CONFIRMED", "Sales Order"),
        ("DONE", "Locked/Done"),
        ("CANCELLED", "Cancelled"),
    )

    DRAFT = "DRAFT"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

    # =========================================================
    # ALLOWED TRANSITIONS
    # =========================================================

    ALLOWED_TRANSITIONS = {
        DRAFT: [
            SENT,
            CONFIRMED,
            CANCELLED,
        ],

        SENT: [
            CONFIRMED,
            CANCELLED,
            DRAFT,
        ],

        CONFIRMED: [
            DONE,
            CANCELLED,
            DRAFT,
        ],

        DONE: [],

        CANCELLED: [],
    }

    # =========================================================
    # STATE CHECKS
    # =========================================================

    def can_transition(self, current_state, new_state):
        """Check whether a workflow transition is allowed."""
        return new_state in self.ALLOWED_TRANSITIONS.get(
            current_state,
            [],
        )

    # =========================================================
    # EDITABILITY
    # =========================================================

    def is_editable(self, order):
        """
        Only DRAFT orders are directly editable.

        SENT, CONFIRMED, DONE and CANCELLED orders require
        a controlled workflow operation.
        """
        return order.status == self.DRAFT

    # =========================================================
    # DELETE RULES
    # =========================================================

    def can_delete(self, order):
        """
        Only DRAFT orders may be hard-deleted.

        Sent/confirmed/done/cancelled orders should remain
        for audit history.
        """
        return order.status == self.DRAFT

    # =========================================================
    # SEND VALIDATION
    # =========================================================

    def can_send(self, order):
        """
        Validate DRAFT -> SENT.
        """
        errors = {}

        if not order.partner_id:
            errors["partner"] = [
                "Order requires a customer before it can be sent."
            ]

        if not order.lines.exists():
            errors["lines"] = [
                "Order requires at least one line item before it can be sent."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # CONFIRMATION VALIDATION
    # =========================================================

    def can_confirm(self, order):
        """
        Validate SENT -> CONFIRMED.
        """
        errors = {}

        if not order.partner_id:
            errors["partner"] = [
                "Sales Order requires a customer."
            ]

        if not order.lines.exists():
            errors["lines"] = [
                "Sales Order requires at least one line item."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # DONE / LOCK VALIDATION
    # =========================================================

    def can_mark_done(self, order):
        """
        Validate CONFIRMED -> DONE.

        DONE is the locked/final operational state.
        """
        errors = {}

        if getattr(order, "amount_residual", 0) > 0:
            errors["payment"] = [
                "Sales Order still has an outstanding balance."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # CANCELLATION VALIDATION
    # =========================================================

    def can_cancel(self, order):
        """
        Validate whether a Sales Order may be cancelled.

        DRAFT / SENT / CONFIRMED:
            May be cancelled if there is no payment allocation
            and no physical delivery progress.

        DONE:
            Cannot be cancelled.

        PARTIAL / COMPLETED delivery:
            Cannot be cancelled. Physical goods must be handled
            through returns.

        This method does NOT:
            - cancel deliveries
            - reverse accounting
            - save the order
            - check user permissions
        """

        errors = {}

        # -----------------------------------------------------
        # Locked state
        # -----------------------------------------------------

        if order.status == self.DONE:
            errors["status"] = [
                "Locked/Done orders cannot be cancelled."
            ]

        # -----------------------------------------------------
        # Payment lock
        # -----------------------------------------------------

        if getattr(order, "payment_state", None) in (
            "partial",
            "paid",
        ):
            errors["payment"] = [
                "Sales Order has payment allocations and cannot "
                "be cancelled. Remove the payment allocation first."
            ]

        # -----------------------------------------------------
        # Delivery lock
        # -----------------------------------------------------

        active_deliveries = (
            order.pickings
            .exclude(status=StockPicking.Status.CANCELLED)
        )

        if active_deliveries.filter(
            status = StockPicking.Status.COMPLETED
        ).exists():
            errors["delivery"] = [
                "Sales Order has delivery progress and cannot "
                "be cancelled. Process delivered goods through "
                "returns instead."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # RESET TO DRAFT VALIDATION
    # =========================================================

    def can_reset_to_draft(self, order):
        """
        Validate SENT/CONFIRMED -> DRAFT.

        Payment allocations and physical delivery progress
        prevent resetting the order.

        Pending deliveries themselves are not a problem;
        the reset operation can cancel those pending deliveries.
        """

        errors = {}

        # -----------------------------------------------------
        # Payment lock
        # -----------------------------------------------------

        if getattr(order, "payment_state", None) in (
            "partial",
            "paid",
        ):
            errors["payment"] = [
                "Sales Order has payment allocations and cannot "
                "be reset to draft."
            ]

        # -----------------------------------------------------
        # Delivery lock
        # -----------------------------------------------------

        active_deliveries = (
            order.pickings
            .exclude(status=StockPicking.Status.CANCELLED)
        )

        if active_deliveries.filter(
            status = StockPicking.Status.COMPLETED
        ).exists():
            errors["delivery"] = [
                "Sales Order has delivery progress and cannot "
                "be reset to draft."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # MAIN TRANSITION METHOD
    # =========================================================

    def transition(self, order, new_state):
        """
        Validate and apply a Sales Order workflow transition.

        This method mutates order.status but does NOT save it.

        The caller is responsible for:
        - saving the order
        - cancelling pending deliveries
        - creating stock operations
        - accounting operations
        - event dispatch
        """

        current_state = order.status

        # -----------------------------------------------------
        # Already in state
        # -----------------------------------------------------

        if current_state == new_state:
            return fail(
                errors={
                    "status": [
                        f"Order is already {current_state}."
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
                    "status": [
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

        if new_state == self.SENT:
            validation = self.can_send(order)

        elif new_state == self.CONFIRMED:
            validation = self.can_confirm(order)

        elif new_state == self.DONE:
            validation = self.can_mark_done(order)

        elif new_state == self.CANCELLED:
            validation = self.can_cancel(order)

        elif new_state == self.DRAFT:
            validation = self.can_reset_to_draft(order)

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

        order.status = new_state

        return ok(
            success=True,
            changed=True,
            old_state=old_state,
            new_state=new_state,
        )

    # =========================================================
    # STATE FLAGS
    # =========================================================

    def get_flags(self, order):
        """
        Return workflow flags for frontend/UI logic.

        These flags describe the state-level possibility.
        Backend operations must still enforce permissions
        and business validation.
        """

        return {
            "editable": (
                self.is_editable(order)
            ),

            "can_delete": (
                self.can_delete(order)
            ),

            "can_send": (
                order.status == self.DRAFT
            ),

            "can_confirm": (
                order.status == self.SENT
            ),

            "can_done": (
                order.status == self.CONFIRMED
            ),

            "can_cancel": (
                order.status in (
                    self.DRAFT,
                    self.SENT,
                    self.CONFIRMED,
                )
            ),

            "can_reset_to_draft": (
                order.status in (
                    self.SENT,
                    self.CONFIRMED,
                )
            ),

            "locked": (
                order.status in (
                    self.DONE,
                    self.CANCELLED,
                )
            ),
        }