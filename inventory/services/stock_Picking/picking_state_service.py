from django.db.models import Count, Q

from core.utils.result import fail, ok
from inventory.models import StockMove, StockPicking


class PickingStateService:
    """
    The single place that decides whether a picking action is allowed.

        picking_state.check(picking, "confirm" | "assign" | "validate" | "cancel")

    returns ok() or fail(errors). Views call check() and then do the work
    (picking.action_confirm / action_assign / validate / cancel) WITHOUT re-checking.
    get_flags() is built from the same check(), so a button is shown exactly when its view
    would accept the request.
    """

    # =========================================================
    # WORKFLOW STATES  (single source of truth: the model)
    # =========================================================
    S = StockPicking.Status

    DRAFT = S.DRAFT
    WAITING = S.WAITING  # Waiting another operation
    CONFIRMED = S.CONFIRMED  # Waiting availability
    ASSIGNED = S.ASSIGNED  # Ready
    COMPLETED = S.COMPLETED  # Done
    CANCELLED = S.CANCELLED

    ACTIONS = ("confirm", "assign", "validate", "cancel")

    # COMPLETED and CANCELLED are terminal states.
    # To undo a COMPLETED picking, create a return transfer instead.
    #
    # StockPicking.validate() is an immediate transfer: it confirms a draft itself and
    # completes every move that is not WAITING, so COMPLETED is reachable from any open state.
    ALLOWED_TRANSITIONS = {
        DRAFT: [WAITING, CONFIRMED, ASSIGNED, COMPLETED, CANCELLED],
        WAITING: [CONFIRMED, ASSIGNED, COMPLETED, CANCELLED],
        CONFIRMED: [ASSIGNED, COMPLETED, CANCELLED],
        ASSIGNED: [COMPLETED, CONFIRMED, CANCELLED],
        COMPLETED: [],
        CANCELLED: [],
    }

    # Used for error keys and messages, derived from picking_type.code.
    LABELS = {
        "incoming": "incoming",
        "outgoing": "delivery",
        "internal": "transfer",
        "return": "return",
        "adjustment": "adjustment",
    }

    def can_transition(self, current_state, new_state):
        """Check whether a workflow transition is allowed."""
        return new_state in self.ALLOWED_TRANSITIONS.get(current_state, [])

    # =========================================================
    # HELPERS
    # =========================================================

    def _label(self, picking):
        return self.LABELS.get(picking.picking_type.code, "picking")

    def _move_counts(self, picking):
        """{status: count} for the picking's moves, in a single query."""
        rows = picking.moves.values("status").annotate(n=Count("id"))
        return {row["status"]: row["n"] for row in rows}

    # =========================================================
    # PER-ACTION RULES (one implementation for all picking types)
    # =========================================================

    def _check_confirm(self, picking, counts):
        """Draft -> confirmed. Available whenever the picking is in DRAFT status."""
        label = self._label(picking)
        if picking.status != self.DRAFT:
            return fail({"status": [f"Only draft {label}s can be confirmed "
                                    f"(this one is {picking.get_status_display()})."]})
        # Remove `if not counts:` so the button is always available in DRAFT,
        # and let the backend action_confirm() raise an error if someone tries to confirm an empty picking.
        return ok()


    def _check_assign(self, picking, counts):
        """Reserve stock. Needs an open, confirmed picking with a move that can actually reserve:
        waiting for availability, or waiting on a move that has since completed (this mirrors
        StockMoveQuerySet.action_assign)."""
        label = self._label(picking)
        if picking.status not in (self.WAITING, self.CONFIRMED, self.ASSIGNED):
            return fail({"status": [f"Cannot reserve stock for a {label} that is "
                                    f"{picking.get_status_display()}; confirm it first."]})
        S = StockMove.Status
        reservable = picking.moves.filter(
            Q(status=S.CONFIRMED) | Q(status=S.WAITING, move_orig_ids__status=S.COMPLETED)
        ).exists()
        if not reservable:
            return fail({label: [f"nothing to reserve: no item of this {label} is waiting for availability"]})
        return ok()

    def can_validate(self, picking, counts=None):
        label = self._label(picking)

        # 1. HARD BLOCK: Draft pickings can NEVER be validated directly
        if picking.status == self.DRAFT:
            return fail({label: [f"Cannot validate a draft {label}; you must confirm it first."]})

        # 2. Proceed with existing move/status checks
        counts = self._move_counts(picking) if counts is None else counts

        if not counts:
            return fail({label: [f"cannot validate {label} without items"]})

        S = StockMove.Status
        ready = sum(n for status, n in counts.items()
                    if status not in (S.COMPLETED, S.CANCELLED, S.WAITING))
        if not ready:
            return fail({label: [f"cannot validate {label}: no items are ready"]})
        return ok()

    def can_cancel(self, picking, counts=None):
        """
        An empty picking, or one with already-cancelled lines, is fine to cancel.
        A completed line is not: StockMove.cancel() refuses it.
        """
        label = self._label(picking)
        counts = self._move_counts(picking) if counts is None else counts

        if counts.get(StockMove.Status.COMPLETED):
            return fail({label: [f"cannot cancel {label} with completed lines; "
                                 "create a reverse move instead"]})
        return ok()

    def _check_validate(self, picking, counts):
        if not self.can_transition(picking.status, self.COMPLETED):
            return fail({"status": [f"Cannot validate a picking that is {picking.get_status_display()}."]})
        return self.can_validate(picking, counts)

    def _check_cancel(self, picking, counts):
        if not self.can_transition(picking.status, self.CANCELLED):
            return fail({"status": [f"Cannot cancel a picking that is {picking.get_status_display()}."]})
        return self.can_cancel(picking, counts)

    # =========================================================
    # THE DECISION POINT
    # =========================================================

    def check(self, picking, action, counts=None):
        """Is `action` allowed on `picking`? Returns ok() or fail(errors). Does not mutate."""
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown picking action '{action}'.")
        counts = self._move_counts(picking) if counts is None else counts
        return getattr(self, f"_check_{action}")(picking, counts)

    # =========================================================
    # TRANSITION CHECK (generic status change)
    # =========================================================

    def transition(self, picking, new_state):
        """
        Validate a generic picking workflow transition. Does NOT mutate or save the picking.
        Prefer check() for the four user actions; this stays for status-level checks.
        """
        current_state = picking.status

        if current_state == new_state:
            return fail(errors={"status": [f"Picking is already {current_state}."]},
                        success=False, changed=False)

        if not self.can_transition(current_state, new_state):
            return fail(errors={"status": [f"Cannot transition from '{current_state}' to '{new_state}'."]},
                        success=False, changed=False)

        validation = ok()
        if new_state == self.COMPLETED:
            validation = self.can_validate(picking)
        elif new_state == self.CANCELLED:
            validation = self.can_cancel(picking)

        if validation.get("errors"):
            return fail(errors=validation["errors"], success=False, changed=False)

        return ok(success=True, changed=True, old_state=current_state, new_state=new_state)

    # =========================================================
    # STATE FLAGS (same rules as check(), so buttons and views never disagree)
    # =========================================================

    def get_flags(self, picking):
        """
        Workflow flags for frontend/UI logic. Backend operations still enforce
        permissions and call check() themselves.
        """
        counts = self._move_counts(picking)

        def allowed(action):
            return not self.check(picking, action, counts).get("errors")

        return {
            "can_confirm": allowed("confirm"),
            "can_assign": allowed("assign"),
            "can_validate": allowed("validate"),
            "can_cancel": allowed("cancel"),
            "locked": picking.status in (self.COMPLETED, self.CANCELLED),
        }