from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from accounting.models import (
    AccountMoveLine,
    PartialReconcile,
)

from accounting.services.reconciliation_service.get_open_reconciliation_lines import (
    get_open_reconciliation_lines,
    _remaining_balance_queryset,
)


class ReconciliationError(Exception):
    """
    Base class for reconciliation-time errors.
    """
    pass


class LineError(ReconciliationError):
    """
    The individual line cannot participate in reconciliation.

    The line is excluded, but other lines continue processing.
    """
    pass


class GroupError(ReconciliationError):
    """
    A group of lines cannot be reconciled together.

    The group is excluded, but other groups continue processing.
    """
    pass


class FatalReconciliationError(ReconciliationError):
    """
    The entire reconciliation operation is unsafe.

    The transaction must be aborted.
    """
    pass


class LineUnavailableError(LineError):
    """
    A requested line is not available for this reconciliation attempt.
    """

    def __init__(self, line_id, reason, detail=None):
        self.line_id = line_id
        self.reason = reason

        super().__init__(
            detail or reason
        )


class ReconciliationService:

    def __init__(self, company,user, line_ids=None):
        self.company = company
        self.user = user

        # --------------------------------------------------------------
        # MODE
        # --------------------------------------------------------------
        #
        # None means automatic mode.
        #
        # Any iterable, including [], means manual mode.
        #
        # Therefore:
        #
        #   line_ids=None -> automatic
        #   line_ids=[]   -> manual, nothing selected
        #
        # --------------------------------------------------------------

        self.is_manual = line_ids is not None

        self.line_ids = (
            {int(line_id) for line_id in line_ids}
            if line_ids is not None
            else set()
        )

        self._reset_state()

    # ==================================================================
    # STATE
    # ==================================================================

    def _reset_state(self):
        """
        Reset all transient reconciliation state.

        A service instance is normally intended to be used for one
        reconciliation operation, but keeping the reset centralized
        prevents stale state if run() is called more than once.
        """

        # Loaded / locked lines.
        self.lines = []

        # Raw groups.
        self.groups = {}

        # Groups that passed validation.
        self.valid_groups = {}

        # Proposed matches.
        #
        # {
        #     (account_id, partner_id): [
        #         {
        #             "debit_line": ...,
        #             "credit_line": ...,
        #             "amount": Decimal(...)
        #         }
        #     ]
        # }
        self.matches = {}

        # Matches that passed validation.
        self.valid_matches = []

        # Created PartialReconcile records.
        self.partial_reconciles = []

        # Errors.
        self.line_errors = {}
        self.group_errors = {}
        self.match_errors = []

    # ==================================================================
    # ERROR HANDLING
    # ==================================================================

    def _record_line_error(self, line_id, error):
        """
        Record the first error for a line.

        Existing errors are preserved.
        """

        self.line_errors.setdefault(
            line_id,
            error,
        )

    # ==================================================================
    # LOAD
    # ==================================================================

    def load_lines(self):
        """
        Load lines that are candidates for reconciliation.

        Manual mode:
            Load only explicitly selected lines.

        Automatic mode:
            Discover all currently open reconciliation lines.
        """

        # --------------------------------------------------------------
        # MANUAL MODE
        # --------------------------------------------------------------

        if self.is_manual:

            # [] explicitly means no selection.
            if not self.line_ids:
                self.lines = []
                return

            qs = (
                AccountMoveLine.objects
                .filter(
                    id__in=self.line_ids,
                    move__company=self.company,
                    move__state="posted",
                    account__allow_reconciliation=True,
                )
                .select_related(
                    "account",
                    "partner",
                    "move",
                )
                .order_by(
                    "account_id",
                    "partner_id",
                    "date",
                    "id",
                )
            )

            self.lines = list(
                _remaining_balance_queryset(qs)
            )

            loaded_ids = {
                line.id
                for line in self.lines
            }

            missing_ids = (
                self.line_ids - loaded_ids
            )

            for line_id in missing_ids:

                self._record_line_error(
                    line_id,
                    LineUnavailableError(
                        line_id,
                        reason="not_found_or_ineligible",
                        detail=(
                            f"Line {line_id} is not available "
                            f"for reconciliation."
                        ),
                    ),
                )

            return

        # --------------------------------------------------------------
        # AUTO MODE
        # --------------------------------------------------------------

        grouped = get_open_reconciliation_lines(
            company=self.company,
        )

        self.lines = [
            line
            for account in grouped.values()
            for partner in account["partners"].values()
            for line in partner["lines"]
        ]

    # ==================================================================
    # LOCK
    # ==================================================================

    def lock_lines(self):
        """
        Re-select loaded lines using SELECT FOR UPDATE.

        This protects the participating AccountMoveLine records against
        concurrent reconciliation operations.

        Must run inside transaction.atomic().
        """

        if not self.lines:
            return

        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError(
                "lock_lines() must be called inside an open "
                "transaction.atomic() block. "
                "Use run() instead."
            )

        requested_ids = {
            line.id
            for line in self.lines
        }

        qs = (
            AccountMoveLine.objects
            .select_for_update()
            .filter(
                id__in=requested_ids,
                move__company=self.company,
                move__state="posted",
                account__allow_reconciliation=True,
            )
            .select_related(
                "account",
                "partner",
                "move",
            )
            .order_by(
                "account_id",
                "partner_id",
                "date",
                "id",
            )
        )

        locked_lines = list(
            _remaining_balance_queryset(qs)
        )

        # --------------------------------------------------------------
        # COMPANY CHECK
        # --------------------------------------------------------------

        for line in locked_lines:

            if line.move.company_id != self.company.id:

                raise FatalReconciliationError(
                    f"Line {line.id} belongs to company "
                    f"{line.move.company_id}, not "
                    f"{self.company.id}."
                )

        # --------------------------------------------------------------
        # FIND LINES THAT BECAME UNAVAILABLE
        # --------------------------------------------------------------

        locked_ids = {
            line.id
            for line in locked_lines
        }

        unavailable_ids = (
            requested_ids - locked_ids
        )

        for line_id in unavailable_ids:

            self._record_line_error(
                line_id,
                LineUnavailableError(
                    line_id,
                    reason="no_longer_eligible",
                    detail=(
                        f"Line {line_id} is no longer available "
                        f"for reconciliation. It may have been "
                        f"reconciled, deleted, moved to an "
                        f"ineligible state, or otherwise become "
                        f"unavailable."
                    ),
                ),
            )

        self.lines = locked_lines

    # ==================================================================
    # GROUP
    # ==================================================================

    def group_lines(self):
        """
        Group lines by:

            account
                ↓
            partner
                ↓
            debit / credit

        Currency is intentionally not included because the current
        accounting design uses company currency for AccountMove.
        """

        groups = {}

        for line in self.lines:

            has_debit = line.debit > Decimal("0")
            has_credit = line.credit > Decimal("0")

            # ----------------------------------------------------------
            # INVALID: BOTH SIDES
            # ----------------------------------------------------------

            if has_debit and has_credit:

                self._record_line_error(
                    line.id,
                    LineError(
                        f"Line {line.id} has both a debit and "
                        f"a credit amount."
                    ),
                )

                continue

            # ----------------------------------------------------------
            # INVALID: NEITHER SIDE
            # ----------------------------------------------------------

            if not has_debit and not has_credit:

                self._record_line_error(
                    line.id,
                    LineError(
                        f"Line {line.id} has neither a debit nor "
                        f"a credit amount."
                    ),
                )

                continue

            # ----------------------------------------------------------
            # SIDE
            # ----------------------------------------------------------

            side = (
                "debit"
                if has_debit
                else "credit"
            )

            # ----------------------------------------------------------
            # GROUP KEY
            # ----------------------------------------------------------
            #
            # Account must match.
            # Partner must match.
            #
            # Currency is not part of the key because AccountMove
            # operates in company currency.
            #
            # ----------------------------------------------------------

            bucket_key = line.partner_id

            account = groups.setdefault(
                line.account_id,
                {},
            )

            bucket = account.setdefault(
                bucket_key,
                {
                    "debit": [],
                    "credit": [],
                },
            )

            bucket[side].append(line)

        self.groups = groups

    # ==================================================================
    # VALIDATE GROUPS
    # ==================================================================

    def validate_groups(self):
        """
        Keep only groups containing both debit and credit lines.

        One-sided groups cannot produce reconciliation matches.
        """

        self.valid_groups = {}
        self.group_errors = {}

        for account_id, buckets in self.groups.items():

            for bucket_key, sides in buckets.items():

                if (
                    not sides["debit"]
                    or not sides["credit"]
                ):

                    self.group_errors[
                        (account_id, bucket_key)
                    ] = GroupError(
                        f"Account {account_id} / "
                        f"partner {bucket_key} "
                        f"has no lines on one side. "
                        f"Nothing can be matched."
                    )

                    continue

                self.valid_groups.setdefault(
                    account_id,
                    {},
                )[bucket_key] = sides

    # ==================================================================
    # MATCHING + ALLOCATION
    # ==================================================================

    def matching_lines(self):
        """
        Match debit and credit lines inside each valid group.

        Matching also determines the reconciliation allocation amount.

        No database writes occur here.

        The algorithm is FIFO based on the deterministic ordering
        established when lines are loaded/locked.
        """

        self.matches = {}

        # --------------------------------------------------------------
        # WORKING BALANCES
        # --------------------------------------------------------------
        #
        # Do not mutate line.remaining.
        #
        # remaining is a queryset annotation representing the database
        # state at the time the lines were loaded/locked.
        #
        # Working balances represent what has been consumed during this
        # in-memory matching pass.
        #
        # --------------------------------------------------------------

        working_remaining = {
            line.id: line.remaining
            for account in self.valid_groups.values()
            for sides in account.values()
            for line in (
                sides["debit"]
                + sides["credit"]
            )
        }

        # --------------------------------------------------------------
        # MATCH GROUPS
        # --------------------------------------------------------------

        for account_id, buckets in self.valid_groups.items():

            for bucket_key, sides in buckets.items():

                debits = sides["debit"]
                credits = sides["credit"]

                matches = []

                debit_index = 0
                credit_index = 0

                while (
                    debit_index < len(debits)
                    and credit_index < len(credits)
                ):

                    debit_line = debits[
                        debit_index
                    ]

                    credit_line = credits[
                        credit_index
                    ]

                    debit_remaining = (
                        working_remaining[
                            debit_line.id
                        ]
                    )

                    credit_remaining = (
                        working_remaining[
                            credit_line.id
                        ]
                    )

                    amount = min(
                        debit_remaining,
                        credit_remaining,
                    )

                    # Defensive protection.
                    if amount <= Decimal("0"):
                        break

                    matches.append({
                        "debit_line": debit_line,
                        "credit_line": credit_line,
                        "amount": amount,
                    })

                    # --------------------------------------------------
                    # CONSUME LOCAL BALANCES
                    # --------------------------------------------------

                    working_remaining[
                        debit_line.id
                    ] -= amount

                    working_remaining[
                        credit_line.id
                    ] -= amount

                    # --------------------------------------------------
                    # MOVE POINTERS
                    # --------------------------------------------------

                    if (
                        working_remaining[
                            debit_line.id
                        ] <= Decimal("0")
                    ):
                        debit_index += 1

                    if (
                        working_remaining[
                            credit_line.id
                        ] <= Decimal("0")
                    ):
                        credit_index += 1

                if matches:

                    self.matches[
                        (account_id, bucket_key)
                    ] = matches

        return self.matches

    # ==================================================================
    # VALIDATE MATCHES
    # ==================================================================

    def validate_matches(self):
        """
        Validate all proposed reconciliation matches.

        No database writes occur here.
        """

        self.valid_matches = []
        self.match_errors = []

        # --------------------------------------------------------------
        # TRACK ALLOCATION
        # --------------------------------------------------------------
        #
        # Allocation is tracked against the original remaining amount
        # so a line cannot be overallocated across multiple matches.
        #
        # --------------------------------------------------------------

        allocated = {}

        # --------------------------------------------------------------
        # FLATTEN MATCHES
        # --------------------------------------------------------------

        matches = [
            match
            for group_matches in self.matches.values()
            for match in group_matches
        ]

        for index, match in enumerate(matches):

            debit_line = match.get(
                "debit_line"
            )

            credit_line = match.get(
                "credit_line"
            )

            amount = match.get(
                "amount"
            )

            # ----------------------------------------------------------
            # STRUCTURE
            # ----------------------------------------------------------

            if (
                debit_line is None
                or credit_line is None
            ):

                self.match_errors.append({
                    "index": index,
                    "reason": "missing_line",
                    "detail": (
                        "Both debit and credit lines "
                        "are required."
                    ),
                    "match": match,
                })

                continue

            if debit_line.id == credit_line.id:

                self.match_errors.append({
                    "index": index,
                    "reason": "same_line",
                    "detail": (
                        f"Line {debit_line.id} cannot be "
                        f"reconciled against itself."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # AMOUNT
            # ----------------------------------------------------------

            if amount is None:

                self.match_errors.append({
                    "index": index,
                    "reason": "missing_amount",
                    "detail": (
                        "A reconciliation amount "
                        "is required."
                    ),
                    "match": match,
                })

                continue

            try:
                amount = Decimal(str(amount))

            except Exception:

                self.match_errors.append({
                    "index": index,
                    "reason": "invalid_amount",
                    "detail": (
                        f"Invalid reconciliation amount: "
                        f"{amount!r}."
                    ),
                    "match": match,
                })

                continue

            if amount <= Decimal("0"):

                self.match_errors.append({
                    "index": index,
                    "reason": "invalid_amount",
                    "detail": (
                        f"Reconciliation amount must be "
                        f"greater than zero; got {amount}."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # COMPANY
            # ----------------------------------------------------------

            if (
                debit_line.move.company_id
                != self.company.id
            ):

                raise FatalReconciliationError(
                    f"Debit line {debit_line.id} belongs "
                    f"to company "
                    f"{debit_line.move.company_id}, not "
                    f"{self.company.id}."
                )

            if (
                credit_line.move.company_id
                != self.company.id
            ):

                raise FatalReconciliationError(
                    f"Credit line {credit_line.id} belongs "
                    f"to company "
                    f"{credit_line.move.company_id}, not "
                    f"{self.company.id}."
                )

            # ----------------------------------------------------------
            # ACCOUNT
            # ----------------------------------------------------------
            #
            # This should already be guaranteed by grouping.
            #
            # Keep the check as a defensive invariant.
            #
            # ----------------------------------------------------------

            if (
                debit_line.account_id
                != credit_line.account_id
            ):

                self.match_errors.append({
                    "index": index,
                    "reason": "different_accounts",
                    "detail": (
                        f"Debit line {debit_line.id} and "
                        f"credit line {credit_line.id} "
                        f"belong to different accounts."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # PARTNER
            # ----------------------------------------------------------
            #
            # This should already be guaranteed by grouping.
            #
            # ----------------------------------------------------------

            if (
                debit_line.partner_id
                != credit_line.partner_id
            ):

                self.match_errors.append({
                    "index": index,
                    "reason": "different_partners",
                    "detail": (
                        f"Debit line {debit_line.id} and "
                        f"credit line {credit_line.id} "
                        f"belong to different partners."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # DEBIT SIDE
            # ----------------------------------------------------------

            debit_allocated = allocated.get(
                debit_line.id,
                Decimal("0"),
            )

            debit_available = (
                debit_line.remaining
                - debit_allocated
            )

            if amount > debit_available:

                self.match_errors.append({
                    "index": index,
                    "reason": "debit_overallocated",
                    "detail": (
                        f"Match allocates {amount} to "
                        f"debit line {debit_line.id}, "
                        f"but only {debit_available} "
                        f"remains available."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # CREDIT SIDE
            # ----------------------------------------------------------

            credit_allocated = allocated.get(
                credit_line.id,
                Decimal("0"),
            )

            credit_available = (
                credit_line.remaining
                - credit_allocated
            )

            if amount > credit_available:

                self.match_errors.append({
                    "index": index,
                    "reason": "credit_overallocated",
                    "detail": (
                        f"Match allocates {amount} to "
                        f"credit line {credit_line.id}, "
                        f"but only {credit_available} "
                        f"remains available."
                    ),
                    "match": match,
                })

                continue

            # ----------------------------------------------------------
            # VALID MATCH
            # ----------------------------------------------------------

            valid_match = {
                **match,
                "amount": amount,
            }

            self.valid_matches.append(
                valid_match
            )

            allocated[
                debit_line.id
            ] = (
                debit_allocated
                + amount
            )

            allocated[
                credit_line.id
            ] = (
                credit_allocated
                + amount
            )

        return self.valid_matches

    # ==================================================================
    # SYNC LINE STATE
    # ==================================================================

    def _sync_line_state(self, line):
        """
        Synchronize AccountMoveLine.reconciled from PartialReconcile.

        PartialReconcile remains the source of truth.
        """

        if line.debit > Decimal("0"):

            matched = (
                line.matched_debit_ids
                .aggregate(
                    total=Sum("amount")
                )
                ["total"]
                or Decimal("0")
            )

            line_amount = line.debit

        elif line.credit > Decimal("0"):

            matched = (
                line.matched_credit_ids
                .aggregate(
                    total=Sum("amount")
                )
                ["total"]
                or Decimal("0")
            )

            line_amount = line.credit

        else:

            raise FatalReconciliationError(
                f"Line {line.id} has neither debit nor credit "
                f"amount while synchronizing reconciliation state."
            )

        reconciled = (
            matched >= line_amount
        )

        if line.reconciled != reconciled:

            line.reconciled = reconciled

            line.save(
                update_fields=[
                    "reconciled",
                ]
            )

    # ==================================================================
    # COMPUTE PAYMENT STATE
    # ==================================================================

    def _compute_payment_state(
        self,
        residual,
        total,
    ):
        """
        Calculate payment state from residual and total amount.

        States:

            paid
            not_paid
            partial

        Zero-total moves are handled explicitly instead of using a
        fake 0.01 denominator.
        """

        residual = (
            residual or Decimal("0")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        total = (
            total or Decimal("0")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        # --------------------------------------------------------------
        # ZERO-TOTAL
        # --------------------------------------------------------------

        if total <= Decimal("0.00"):

            return (
                "paid"
                if residual <= Decimal("0.00")
                else "not_paid"
            )

        # --------------------------------------------------------------
        # NORMAL TOTAL
        # --------------------------------------------------------------

        if residual <= Decimal("0.00"):
            return "paid"

        if residual >= total:
            return "not_paid"

        return "partial"

    # ==================================================================
    # SYNC MOVE STATE
    # ==================================================================

    def _sync_move_state(
        self,
        move,
        reconcile_date,
    ):
        """
        Synchronize AccountMove reconciliation/payment state.

        Derived from PartialReconcile records.

        NOTE:
        This assumes move.amount_total represents the amount whose
        reconciliation should drive the move's residual.

        If payment AccountMoves use a different residual model, payment
        synchronization should be separated into its own domain-specific
        method.
        """

        total_matched = (
            PartialReconcile.objects
            .filter(
                Q(debit_line__move=move)
                | Q(credit_line__move=move)
            )
            .aggregate(
                total=Sum("amount")
            )
            ["total"]
            or Decimal("0")
        )

        amount_total = (
            move.amount_total
            or Decimal("0")
        )

        amount_residual = max(
            Decimal("0"),
            amount_total - total_matched,
        )

        payment_state = (
            self._compute_payment_state(
                amount_residual,
                amount_total,
            )
        )

        reconciled = (
            amount_residual
            <= Decimal("0.00")
        )

        move.amount_residual = (
            amount_residual
        )

        move.payment_state = (
            payment_state
        )

        move.reconciled = (
            reconciled
        )

        move.reconciliation_date = (
            reconcile_date
            if reconciled
            else None
        )

        move.save(
            update_fields=[
                "amount_residual",
                "payment_state",
                "reconciled",
                "reconciliation_date",
            ]
        )

        move.sync_origin_reconciliation_state(payment_state, amount_residual)

        # --------------------------------------------------------------
        # SALES INVOICE
        # --------------------------------------------------------------

        if hasattr(move, "sales_invoice"):

            invoice = move.sales_invoice

            invoice.payment_state = (
                payment_state
            )

            invoice.amount_residual = (
                amount_residual
            )

            invoice.save(
                update_fields=[
                    "payment_state",
                    "amount_residual",
                ]
            )

    # ==================================================================
    # EXECUTE
    # ==================================================================

    def execute_reconciliations(
        self,
        reconcile_date=None,
    ):
        """
        Persist validated reconciliation matches.

        Responsibilities:

            1. Create PartialReconcile records.
            2. Synchronize affected AccountMoveLine state.
            3. Synchronize affected AccountMove state.
            4. Synchronize related invoice state.

        This method performs database writes and MUST run inside
        transaction.atomic().

        Any unexpected database/domain error is allowed to propagate so
        the surrounding transaction can roll back.
        """

        reconcile_date = (
            reconcile_date
            or timezone.now().date()
        )

        self.partial_reconciles = []

        if not self.valid_matches:
            return []

        touched_lines = {}
        touched_moves = {}

        # --------------------------------------------------------------
        # CREATE PARTIAL RECONCILES
        # --------------------------------------------------------------

        for match in self.valid_matches:

            debit_line = match[
                "debit_line"
            ]

            credit_line = match[
                "credit_line"
            ]

            amount = match[
                "amount"
            ]

            # ----------------------------------------------------------
            # DEFENSIVE EXECUTION CHECKS
            # ----------------------------------------------------------

            if amount <= Decimal("0"):

                raise FatalReconciliationError(
                    f"Cannot create reconciliation "
                    f"with amount {amount}."
                )

            if (
                debit_line.id
                == credit_line.id
            ):

                raise FatalReconciliationError(
                    f"Line {debit_line.id} cannot "
                    f"reconcile against itself."
                )

            if (
                debit_line.account_id
                != credit_line.account_id
            ):

                raise FatalReconciliationError(
                    f"Lines {debit_line.id} and "
                    f"{credit_line.id} belong to "
                    f"different accounts."
                )

            if (
                debit_line.partner_id
                != credit_line.partner_id
            ):

                raise FatalReconciliationError(
                    f"Lines {debit_line.id} and "
                    f"{credit_line.id} belong to "
                    f"different partners."
                )

            if (
                debit_line.move.company_id
                != self.company.id
                or credit_line.move.company_id
                != self.company.id
            ):

                raise FatalReconciliationError(
                    "Cannot reconcile lines belonging "
                    "to another company."
                )

            # ----------------------------------------------------------
            # CREATE PARTIAL
            # ----------------------------------------------------------

            partial = (
                PartialReconcile.objects.create(
                    debit_line=debit_line,
                    credit_line=credit_line,
                    amount=amount,
                    created_by=self.user,
                    company=self.company,
                )
            )

            self.partial_reconciles.append(
                partial
            )

            # ----------------------------------------------------------
            # TOUCHED LINES
            # ----------------------------------------------------------

            touched_lines[
                debit_line.id
            ] = debit_line

            touched_lines[
                credit_line.id
            ] = credit_line

            # ----------------------------------------------------------
            # TOUCHED MOVES
            # ----------------------------------------------------------

            touched_moves[
                debit_line.move_id
            ] = debit_line.move

            touched_moves[
                credit_line.move_id
            ] = credit_line.move

        # --------------------------------------------------------------
        # SYNC LINE STATE
        # --------------------------------------------------------------

        for line in touched_lines.values():

            self._sync_line_state(
                line
            )

        # --------------------------------------------------------------
        # SYNC MOVE STATE
        # --------------------------------------------------------------

        for move in touched_moves.values():

            self._sync_move_state(
                move,
                reconcile_date,
            )

        return self.partial_reconciles

    # ==================================================================
    # RESULT
    # ==================================================================

    def build_result(self):
        """
        Build the final reconciliation result.

        No database writes occur here.

        Note:
        The returned model instances are intended for internal/service
        consumption. Serialize them at the HTTP/API boundary rather
        than expecting this dictionary to be directly JSON serializable.
        """

        return {
            "success": bool(
                self.partial_reconciles
            ),

            "partial_reconciles": (
                self.partial_reconciles
            ),

            "line_errors": (
                self.line_errors
            ),

            "group_errors": (
                self.group_errors
            ),

            "match_errors": (
                self.match_errors
            ),

            "matched_count": len(
                self.partial_reconciles
            ),
        }

    # ==================================================================
    # RUN
    # ==================================================================

    def run(self, reconcile_date=None):
        """
        Execute the complete reconciliation pipeline.

        Pipeline:

            load
                ↓
            lock
                ↓
            group
                ↓
            validate groups
                ↓
            match + allocate
                ↓
            validate matches
                ↓
            execute
                ↓
            commit
                ↓
            result
        """

        self._reset_state()

        reconcile_date = (
            reconcile_date
            or timezone.now().date()
        )

        with transaction.atomic():

            # ----------------------------------------------------------
            # LOAD
            # ----------------------------------------------------------

            self.load_lines()

            # ----------------------------------------------------------
            # LOCK
            # ----------------------------------------------------------

            self.lock_lines()

            # ----------------------------------------------------------
            # GROUP
            # ----------------------------------------------------------

            self.group_lines()

            # ----------------------------------------------------------
            # VALIDATE GROUPS
            # ----------------------------------------------------------

            self.validate_groups()

            # ----------------------------------------------------------
            # MATCH + ALLOCATE
            # ----------------------------------------------------------

            self.matching_lines()

            # ----------------------------------------------------------
            # VALIDATE MATCHES
            # ----------------------------------------------------------

            self.validate_matches()

            # ----------------------------------------------------------
            # EXECUTE
            # ----------------------------------------------------------

            self.execute_reconciliations(
                reconcile_date=reconcile_date,
            )

        # --------------------------------------------------------------
        # TRANSACTION HAS COMMITTED SUCCESSFULLY
        # --------------------------------------------------------------

        return self.build_result()