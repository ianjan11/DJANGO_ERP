from dataclasses import dataclass
from typing import Dict, Any
from datetime import datetime
import uuid
from core.events import EventContext
from core.events.base import Event


def create_event(
    event_type: str,
    payload: dict | None = None,
    user_id: int | None = None,
    source: str = "system",
    correlation_id: str | None = None,
):
    return Event(
        id=str(uuid.uuid4()),
        type=event_type,
        context=EventContext(
            user_id=user_id,
            source=source,
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload=payload or {},
        timestamp=datetime.utcnow(),
    )


