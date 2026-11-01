from enum import Enum


class SystemEventType(str, Enum):

    # ─── Lifecycle / System ───
    SYSTEM_START = "system.start"
    SYSTEM_SHUTDOWN = "system.shutdown"

    # ─── Event Bus / Infrastructure ───
    EVENT_DISPATCHED = "event.dispatched"
    EVENT_HANDLED = "event.handled"
    EVENT_FAILED = "event.failed"

    # ─── Handler Execution ───
    HANDLER_STARTED = "handler.started"
    HANDLER_SUCCESS = "handler.success"
    HANDLER_FAILED = "handler.failed"

    # ─── Validation / Safety ───
    EVENT_INVALID = "event.invalid"
    EVENT_REJECTED = "event.rejected"

    # ─── Logging / Audit ───
    AUDIT_LOG_CREATED = "audit.log.created"