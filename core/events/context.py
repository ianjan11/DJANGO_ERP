from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import uuid


@dataclass
class EventContext:

    # Who triggered the action
    user_id: Optional[int] = None

    # Where event came from
    source: str = "system"

    # Trace related events together
    correlation_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    # Unique request identifier
    request_id: Optional[str] = None

    # Multi-company ERP support later
    company_id: Optional[int] = None

    # Extra flexible metadata
    meta: Dict[str, Any] = field(default_factory=dict)