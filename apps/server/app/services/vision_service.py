from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.contracts.media import FramePayload
from app.contracts.model_io import VisionInput, VisionResult
from app.core.session_state import SessionState
from app.providers.vision.base import VisionProvider


class VisionService:
    def __init__(self, provider: VisionProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def _cache_valid(self, session: SessionState, scene_hash: str | None) -> bool:
        if not session.last_visual_summary or not session.last_visual_summary_at:
            return False
        if scene_hash and session.last_scene_hash and scene_hash != session.last_scene_hash:
            return False
        expires_at = session.last_visual_summary_at + timedelta(
            seconds=self.settings.vision_cache_ttl_seconds
        )
        return datetime.now(timezone.utc) < expires_at

    async def analyze_frame(
        self,
        session: SessionState,
        frame: FramePayload,
        prompt: str,
    ) -> tuple[VisionResult, bool]:
        encoded_size = len(frame.data_base64)
        session.cost_meter.add_frame(encoded_size)

        if frame.capture_reason != "focus_roi" and self._cache_valid(session, frame.scene_hash):
            return (
                VisionResult(
                    summary=session.last_visual_summary or "",
                    confidence=0.72,
                    raw={"cache": True},
                ),
                True,
            )

        mode = "focus" if frame.capture_reason == "focus_roi" else "normal"
        result = await self.provider.analyze(
            VisionInput(
                image_base64=frame.data_base64,
                mime=frame.mime,
                prompt=prompt,
                mode=mode,
                metadata={
                    "frame_id": frame.frame_id,
                    "capture_reason": frame.capture_reason,
                    "width": frame.width,
                    "height": frame.height,
                    "quality": frame.quality,
                },
            )
        )
        session.last_visual_summary = result.summary
        session.last_visual_summary_at = datetime.now(timezone.utc)
        session.last_scene_hash = frame.scene_hash
        session.cost_meter.vision_calls += 1
        session.cost_meter.mode = "focus" if mode == "focus" else "active"
        return result, False

