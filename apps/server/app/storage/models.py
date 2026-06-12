from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionLog:
    session_id: str
    created_at: datetime
    event_count: int = 0

