from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.cost_meter import CostMeter


SessionStatus = Literal["sleeping", "awake", "listening", "thinking", "speaking", "interrupted"]


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:16]}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: SessionStatus = "sleeping"
    wake_word: str = "阿斯塔"
    last_user_text: str | None = None
    last_visual_summary: str | None = None
    last_visual_summary_at: datetime | None = None
    last_scene_hash: str | None = None
    response_in_progress: bool = False
    interrupted_count: int = 0
    cost_meter: CostMeter = Field(default_factory=CostMeter)

    def public_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "wake_word": self.wake_word,
            "last_user_text": self.last_user_text,
            "last_visual_summary": self.last_visual_summary,
            "response_in_progress": self.response_in_progress,
            "interrupted_count": self.interrupted_count,
            "cost": self.cost_meter.model_dump(),
        }

