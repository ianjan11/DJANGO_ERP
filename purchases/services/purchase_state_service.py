from decimal import Decimal

from core.utils.result import ok, fail
from inventory.models import StockPicking


class PurchaseOrdersStateService:
    """
    Controls purchase order workflow state and transitions.

    Responsibilities:
    - state transitions
    - workflow locks
    - edit permissions
    - send/approval guards
    - cancellation rules
    - reset-to-draft rules

    Does NOT:
    - update database rows
    - calculate totals
    - calculate stock
    - cancel shipments
    - render templates
    """

    # =========================================================
    # WORKFLOW STATES
    # =========================================================

    STATUS_CHOICES = (
        ("DRAFT", "RFQ"),
        ("SENT", "RFQ Sent"),
        ("TO_APPROVE", "To Approve"),
        ("PURCHASE", "Purchase Order"),
        ("DONE", "Locked/Done"),
        ("CANCELLED", "Cancelled"),
    )

    DRAFT = "DRAFT"
    SENT = "SENT"
    TO_APPROVE = "TO_APPROVE"
    PURCHASE = "PURCHASE"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

    # =========================================================
    # ALLOWED TRANSITIONS
    # =========================================================

    ALLOWED_TRANSITIONS = {
        DRAFT: [
            SENT,
            TO_APPROVE,
            PURCHASE,
            CANCELLED,
        ],

        SENT: [
            TO_APPROVE,
            CANCELLED,
            DRAFT,
        ],

        TO_APPROVE: [
            PURCHASE,
            CANCELLED,
            DRAFT,
        ],

        PURCHASE: [
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
        """
        Check whether a workflow transition is allowed.
        """
        return new_state in self.ALLOWED_TRANSITIONS.get(
            current_state,
            []
        )

    # =========================================================
    # EDITABILITY
    # =========================================================

    def is_editable(self, order):
        """
        Only DRAFT purchase orders are directly editable.
        """
        return order.status == self.DRAFT

    # =========================================================
    # DELETE RULES
    # =========================================================

    def can_delete(self, order):
        """
        Only untouched DRAFT orders may be hard deleted.
        """
        return order.status == self.DRAFT

    # =========================================================
    # SEND VALIDATION
    # =========================================================

    def can_send(self, order):
        """
        Validation before sending an RFQ.
        DRAFT -> SENT
        """
        errors = {}

        if not order.partner_id:
            errors["partner"] = [
                "RFQ requires a vendor before it can be sent."
            ]

        if not order.lines.exists():
            errors["lines"] = [
                "RFQ requires at least one line item before it can be sent."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # TO_APPROVE VALIDATION
    # =========================================================

    def can_confirm(self, order):
        """
        Validation before moving an RFQ into the approval stage.

        SENT -> TO_APPROVE
        """
        errors = {}

        if not order.partner_id:
            errors["partner"] = [
                "Purchase Order requires a vendor."
            ]

        if not order.lines.exists():
            errors["lines"] = [
                "Purchase Order requires at least one line item."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # PURCHASE VALIDATION
    # =========================================================

    def can_approve(self, order):
        """
        Validation before confirming the purchase order.

        TO_APPROVE -> PURCHASE
        """
        errors = {}

        if not order.partner_id:
            errors["partner"] = [
                "Purchase Order requires a vendor."
            ]

        if not order.lines.exists():
            errors["lines"] = [
                "Purchase Order requires at least one line item."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # DONE / LOCK VALIDATION
    # =========================================================

    def can_mark_done(self, order):
        """
        Validation before permanently locking the purchase order.
        """
        errors = {}

        if getattr(order, "amount_residual", 0) > 0:
            errors["payment"] = [
                "Purchase Order still has an outstanding balance."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # CANCELLATION VALIDATION
    # =========================================================

    def can_cancel(self, order):
        """
        Validation before cancelling a purchase order.

        Cancellation is allowed only while there has been no
        physical receiving.

        DONE is permanently locked.

        Payment rules should be added here if your accounting
        workflow requires payment allocations to be removed
        before cancellation.
        """

        errors = {}

        # -----------------------------------------------------
        # 1. DONE orders are permanently locked
        # -----------------------------------------------------

        if order.status == self.DONE:
            errors["status"] = [
                "Locked/Done purchase orders cannot be cancelled."
            ]

        # -----------------------------------------------------
        # 2. Physical receiving is irreversible
        # -----------------------------------------------------


        active_shipments = (
            order.pickings
            .exclude(status=StockPicking.Status.CANCELLED)
        )

        if active_shipments.filter(
                status=StockPicking.Status.COMPLETED
        ).exists():
            errors["receipt"] = [
                "Purchase order has received goods and cannot "
                "be cancelled. Process the received goods through "
                "returns instead."
            ]


        # -----------------------------------------------------
        # 3. Payment rule
        # -----------------------------------------------------

        if getattr(order, "payment_state", None) in ("partial", "paid"):
            errors["payment"] = [
                "Purchase order has payment allocations and "
                "cannot be cancelled. Remove the payment "
                "allocation first."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # RESET-TO-DRAFT VALIDATION
    # =========================================================

    def can_reset_to_draft(self, order):
        """
        Validation before resetting an order back to DRAFT.

        Allowed source states:
            SENT
            TO_APPROVE
            PURCHASE

        Physical receiving prevents reset.

        Payment allocations may also prevent reset if your
        accounting workflow requires them to be removed first.
        """

        errors = {}

        # -----------------------------------------------------
        # 1. Payment allocations
        # -----------------------------------------------------

        if getattr(order, "payment_state", None) in (
            "partial",
            "paid",
        ):
            errors["payment"] = [
                "Purchase order has payment allocations and "
                "cannot be reset to draft."
            ]

        # -----------------------------------------------------
        # 2. Physical receiving
        # -----------------------------------------------------

        active_shipments = (
            order.pickings
            .exclude(status=StockPicking.Status.CANCELLED)
        )

        if active_shipments.filter(
                status=StockPicking.Status.COMPLETED
        ).exists():
            errors["receipt"] = [
                "Purchase order has received goods and "
                "cannot be reset to draft."
            ]

        if errors:
            return fail(errors=errors)

        return ok()

    # =========================================================
    # MAIN TRANSITION METHOD
    # =========================================================

    def transition(self, order, new_state):
        """
        Apply a workflow transition.

        This method:
        - validates the transition
        - runs state-specific business validation
        - mutates order.status

        It does NOT call save().
        The caller is responsible for persistence.
        """

        current_state = order.status

        # -----------------------------------------------------
        # Already in requested state
        # -----------------------------------------------------

        if current_state == new_state:
            return fail(
                errors={
                    "status": [
                        f"Purchase order is already {current_state}."
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
                        f"'{current_state}' to '{new_state}'."
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

        elif new_state == self.TO_APPROVE:

            validation = self.can_confirm(order)

        elif new_state == self.PURCHASE:

            validation = self.can_approve(order)

        elif new_state == self.DONE:

            validation = self.can_mark_done(order)

        elif new_state == self.CANCELLED:

            validation = self.can_cancel(order)

        elif (
            new_state == self.DRAFT
            and current_state in (
                self.SENT,
                self.TO_APPROVE,
                self.PURCHASE,
            )
        ):

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
        Return workflow flags for UI/business logic.
        """

        return {
            "editable": order.status == self.DRAFT,

            "can_delete": order.status == self.DRAFT,

            "can_send": order.status == self.DRAFT,

            "can_confirm": order.status == self.SENT,

            "can_approve": order.status == self.TO_APPROVE,

            "can_done": order.status == self.PURCHASE,

            "can_cancel": order.status in (
                self.DRAFT,
                self.SENT,
                self.TO_APPROVE,
                self.PURCHASE,
            ),

            "locked": order.status in (
                self.DONE,
                self.CANCELLED,
            ),
        }