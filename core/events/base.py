from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime
import uuid

from core.events.context import EventContext


@dataclass
class Event:

    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    type: str = ""

    # Global metadata object
    context: EventContext = field(
        default_factory=EventContext
    )

    # Business data
    payload: Dict[str, Any] = field(
        default_factory=dict
    )

    timestamp: datetime = field(
        default_factory=datetime.utcnow
    )

    def get(self, key, default=None):
        return self.payload.get(key, default)