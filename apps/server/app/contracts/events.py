from typing import Any, Literal
from uuid import uuid4
import time

from pydantic import BaseModel, ConfigDict, Field


ClientEventType = Literal[
    "client.session.start",
    "client.session.end",
    "client.wake.detected",
    "client.wake.sleep",
    "client.user.text",
    "client.user.speech.partial",
    "client.user.speech.final",
    "client.media.frame",
    "client.media.scene_changed",
    "client.media.audio_chunk",
    "client.control.interrupt",
    "client.control.cancel_response",
    "client.control.confirm",
    "client.control.reject",
    "client.debug.ping",
]

ServerEventType = Literal[
    "server.session.ready",
    "server.session.state",
    "assistant.text.delta",
    "assistant.text.final",
    "assistant.audio.chunk",
    "assistant.audio.done",
    "assistant.avatar.state",
    "assistant.avatar.expression",
    "assistant.avatar.motion",
    "assistant.avatar.lipsync",
    "vision.summary",
    "vision.need_focus",
    "vision.error",
    "cost.update",
    "debug.log",
    "error",
]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:16]}")
    type: ClientEventType | ServerEventType
    session_id: str
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    payload: dict[str, Any] = Field(default_factory=dict)


def make_event(
    event_type: ServerEventType,
    session_id: str,
    payload: dict[str, Any] | None = None,
) -> EventEnvelope:
    return EventEnvelope(type=event_type, session_id=session_id, payload=payload or {})
