from typing import Literal

from pydantic import BaseModel, Field


CaptureReason = Literal[
    "wake_snapshot",
    "visual_question",
    "scene_changed",
    "manual_debug",
    "focus_roi",
    "periodic_low_cost",
    "screen_low_fps",
    "screen_stream",
    "camera_stream",
    "screen_focus",
]


class FramePayload(BaseModel):
    frame_id: str
    mime: str = "image/jpeg"
    width: int
    height: int
    quality: float = 0.72
    capture_reason: CaptureReason
    scene_hash: str | None = None
    data_base64: str = Field(min_length=1)
