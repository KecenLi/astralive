import asyncio
from datetime import datetime, timedelta, timezone
import logging

from app.config import Settings
from app.contracts.media import FramePayload
from app.contracts.model_io import VisionInput, VisionResult
from app.core.session_state import SessionState
from app.providers.vision.base import VisionProvider


logger = logging.getLogger(__name__)


class VisionService:
    def __init__(self, provider: VisionProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def _cache_valid(self, session: SessionState, scene_hash: str | None) -> bool:
        if not scene_hash or not session.last_scene_hash:
            return False
        if not session.last_visual_summary or not session.last_visual_summary_at:
            return False
        if scene_hash != session.last_scene_hash:
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

        is_focus_frame = frame.capture_reason in {"focus_roi", "screen_focus"}
        if not is_focus_frame and self._cache_valid(session, frame.scene_hash):
            return (
                VisionResult(
                    summary=session.last_visual_summary or "",
                    confidence=0.72,
                    raw={"cache": True},
                ),
                True,
            )

        mode = "focus" if is_focus_frame else "normal"
        try:
            result = await asyncio.wait_for(
                self.provider.analyze(
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
                ),
                timeout=self.settings.vision_request_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision provider failed; frame skipped: %s", exc)
            summary = session.last_visual_summary or "视觉服务暂时不可用，已跳过本帧，不影响语音对话。"
            session.last_visual_summary = summary
            session.last_visual_summary_at = datetime.now(timezone.utc)
            session.last_scene_hash = frame.scene_hash
            return VisionResult(summary=summary, confidence=0.0, raw={"error": str(exc)}), False

        session.last_visual_summary = result.summary
        session.last_visual_summary_at = datetime.now(timezone.utc)
        session.last_scene_hash = frame.scene_hash
        session.cost_meter.vision_calls += 1
        session.cost_meter.mode = "focus" if mode == "focus" else "active"
        return result, False
