from collections import deque
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, PrivateAttr

from app.contracts.model_io import ChatMessage
from app.core.cost_meter import CostMeter


SessionStatus = Literal["sleeping", "awake", "listening", "thinking", "speaking", "interrupted"]

# Upper bound on how many recent visual frame ids we remember for candidate
# dedup. Keeps a long soak session from growing this set without bound while
# still catching the duplicates that matter (frames arrive close together).
VISUAL_CANDIDATE_FRAME_MEMORY = 512


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:16]}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: SessionStatus = "sleeping"
    wake_word: str = "小七"
    last_user_text: str | None = None
    last_visual_summary: str | None = None
    camera_visual_summary: str | None = None
    screen_visual_summary: str | None = None
    fused_visual_summary: str | None = None
    visual_self_check_notice: str | None = None
    last_visual_summary_at: datetime | None = None
    last_scene_hash: str | None = None
    visual_summary_at_by_source: dict[str, datetime] = Field(default_factory=dict)
    scene_hash_by_source: dict[str, str] = Field(default_factory=dict)
    response_in_progress: bool = False
    interrupted_count: int = 0
    cost_meter: CostMeter = Field(default_factory=CostMeter)
    history: list[ChatMessage] = Field(default_factory=list)

    # Bounded LRU of recently seen frame ids. The deque enforces the size cap
    # and the set gives O(1) membership; both are kept in sync via
    # register_visual_candidate_frame. Excluded from serialization.
    _visual_candidate_frame_ids: set[str] = PrivateAttr(default_factory=set)
    _visual_candidate_frame_order: deque[str] = PrivateAttr(default_factory=lambda: deque(maxlen=VISUAL_CANDIDATE_FRAME_MEMORY))

    def register_visual_candidate_frame(self, frame_id: str) -> bool:
        """Record a frame id; return True if it was not seen recently.

        Empty ids are always treated as new (cannot be deduped). The memory is
        bounded to VISUAL_CANDIDATE_FRAME_MEMORY entries; the oldest id is
        evicted from both structures when the cap is exceeded.
        """
        if not frame_id:
            return True
        if frame_id in self._visual_candidate_frame_ids:
            return False
        if len(self._visual_candidate_frame_order) >= VISUAL_CANDIDATE_FRAME_MEMORY:
            evicted = self._visual_candidate_frame_order.popleft()
            self._visual_candidate_frame_ids.discard(evicted)
        self._visual_candidate_frame_order.append(frame_id)
        self._visual_candidate_frame_ids.add(frame_id)
        return True

    def append_history_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        max_messages: int = 12,
        max_chars: int = 4000,
    ) -> None:
        if user_text.strip():
            self.history.append(ChatMessage(role="user", content=user_text.strip()))
        if assistant_text.strip():
            self.history.append(ChatMessage(role="assistant", content=assistant_text.strip()))
        self.trim_history(max_messages=max_messages, max_chars=max_chars)

    def history_window(self, *, max_messages: int = 12, max_chars: int = 4000) -> list[ChatMessage]:
        max_messages = max(0, max_messages)
        max_chars = max(0, max_chars)
        if max_messages == 0 or max_chars == 0:
            return []

        window: list[ChatMessage] = []
        total_chars = 0
        for item in reversed(self.history[-max_messages:]):
            content = item.content.strip()
            if not content:
                continue
            if total_chars + len(content) > max_chars:
                if window:
                    break
                content = content[-max_chars:]
                item = ChatMessage(role=item.role, content=content)
            window.append(item)
            total_chars += len(item.content)
            if len(window) >= max_messages:
                break
        return list(reversed(window))

    def trim_history(self, *, max_messages: int = 12, max_chars: int = 4000) -> None:
        max_messages = max(0, max_messages)
        max_chars = max(0, max_chars)
        if max_messages == 0 or max_chars == 0:
            self.history.clear()
            return
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]
        while self.history and sum(len(item.content) for item in self.history) > max_chars:
            self.history.pop(0)

    def visual_summary_for_source(self, source: str) -> str | None:
        normalized = _normalize_visual_source(source)
        if normalized == "camera":
            return self.camera_visual_summary
        if normalized == "screen":
            return self.screen_visual_summary
        return self.last_visual_summary

    def visual_summary_at_for_source(self, source: str) -> datetime | None:
        normalized = _normalize_visual_source(source)
        return self.visual_summary_at_by_source.get(normalized)

    def scene_hash_for_source(self, source: str) -> str | None:
        normalized = _normalize_visual_source(source)
        return self.scene_hash_by_source.get(normalized)

    def update_visual_summary(self, source: str, summary: str, scene_hash: str | None = None) -> None:
        normalized = _normalize_visual_source(source)
        timestamp = datetime.now(timezone.utc)
        summary = summary.strip()
        if normalized == "camera":
            self.camera_visual_summary = summary
        elif normalized == "screen":
            self.screen_visual_summary = summary
        else:
            self.last_visual_summary = summary
        self.visual_summary_at_by_source[normalized] = timestamp
        if scene_hash:
            self.scene_hash_by_source[normalized] = scene_hash

        self.fused_visual_summary = self._build_fused_visual_summary()
        self.last_visual_summary = summary or self.last_visual_summary
        self.last_visual_summary_at = timestamp
        self.last_scene_hash = scene_hash or self.last_scene_hash

    def _build_fused_visual_summary(self) -> str | None:
        camera = self.camera_visual_summary
        screen = self.screen_visual_summary
        if camera and screen:
            return f"摄像头：{camera}\n屏幕：{screen}"
        if camera:
            return camera
        if screen:
            return screen
        if not self.last_visual_summary:
            return None
        return self.last_visual_summary

    def visual_context_public(self) -> dict:
        return {
            "camera": self.camera_visual_summary,
            "screen": self.screen_visual_summary,
            "fused": self.fused_visual_summary or self.last_visual_summary,
            "updated_at": {
                source: value.isoformat()
                for source, value in self.visual_summary_at_by_source.items()
            },
        }

    def visual_prompt_context(self) -> str | None:
        context = self.visual_context_public()
        lines: list[str] = []
        camera = context.get("camera")
        screen = context.get("screen")
        fused = context.get("fused")
        if camera:
            lines.append(f"摄像头最近画面：{camera}")
        if screen:
            lines.append(f"屏幕最近画面：{screen}")
        if fused:
            lines.append(f"融合视觉摘要：{fused}")
        return "\n".join(lines) if lines else None

    def public_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "wake_word": self.wake_word,
            "last_user_text": self.last_user_text,
            "last_visual_summary": self.last_visual_summary,
            "visual_context": self.visual_context_public(),
            "visual_self_check_notice": self.visual_self_check_notice,
            "response_in_progress": self.response_in_progress,
            "interrupted_count": self.interrupted_count,
            "history_turns": len(self.history) // 2,
            "cost": self.cost_meter.model_dump(),
        }


def _normalize_visual_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized.startswith("camera"):
        return "camera"
    if normalized.startswith("screen"):
        return "screen"
    if normalized in {"focus_roi", "visual_question"}:
        return "camera"
    if normalized in {"screen_focus", "screen_low_fps", "screen_stream"}:
        return "screen"
    return normalized or "general"
