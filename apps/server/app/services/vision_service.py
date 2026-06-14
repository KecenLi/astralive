import asyncio
from datetime import datetime, timedelta, timezone
import logging

from app.config import Settings
from app.contracts.media import FramePayload
from app.contracts.model_io import VisionInput, VisionResult
from app.core.cost_estimator import CostEstimator
from app.core.session_state import SessionState
from app.providers.vision.base import VisionProvider


logger = logging.getLogger(__name__)


class VisionService:
    def __init__(self, provider: VisionProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings
        self.cost_estimator = CostEstimator.from_settings(settings)

    def _cache_valid(self, session: SessionState, scene_hash: str | None) -> bool:
        if not scene_hash or not session.last_scene_hash:
            return False
        if not session.last_visual_summary or not session.last_visual_summary_at:
            return False
        if _normalized_hash_distance(scene_hash, session.last_scene_hash) > self.settings.scene_change_threshold:
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
        *,
        commit: bool = True,
    ) -> tuple[VisionResult, bool]:
        encoded_size = len(frame.data_base64)
        session.cost_meter.add_frame(encoded_size)

        is_focus_frame = frame.capture_reason in {"focus_roi", "screen_focus"}
        if not is_focus_frame and self._cache_valid(session, frame.scene_hash):
            session.cost_meter.scene_cache_hits += 1
            session.cost_meter.add_saved_vision_call(
                cost_usd=self.cost_estimator.estimate(
                    provider=self.settings.vision_provider,
                    model=_vision_model_name(self.settings),
                    input_text=prompt,
                    output_text=session.last_visual_summary,
                ).cost_usd
            )
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
        except TimeoutError as exc:
            detail = f"vision provider timed out after {self.settings.vision_request_timeout_seconds:.1f}s"
            logger.warning("vision provider failed; frame skipped: %s", detail)
            summary = session.last_visual_summary or "视觉服务暂时不可用，已跳过本帧，不影响语音对话。"
            result = VisionResult(
                summary=summary,
                confidence=0.0,
                raw={
                    "error": detail,
                    "exception_type": type(exc).__name__,
                    "timeout_seconds": self.settings.vision_request_timeout_seconds,
                },
            )
            if commit:
                self.apply_frame_result(session, frame, result)
            return result, False
        except Exception as exc:  # noqa: BLE001
            detail = str(exc) or type(exc).__name__
            logger.warning("vision provider failed; frame skipped: %s", detail)
            summary = session.last_visual_summary or "视觉服务暂时不可用，已跳过本帧，不影响语音对话。"
            result = VisionResult(
                summary=summary,
                confidence=0.0,
                raw={"error": detail, "exception_type": type(exc).__name__},
            )
            if commit:
                self.apply_frame_result(session, frame, result)
            return result, False

        session.cost_meter.vision_calls += 1
        session.cost_meter.add_estimate(
            self.cost_estimator.estimate(
                raw=result.raw,
                input_text=prompt,
                output_text=result.summary,
            )
        )
        if commit:
            self.apply_frame_result(session, frame, result)
        return result, False

    def apply_frame_result(self, session: SessionState, frame: FramePayload, result: VisionResult) -> None:
        session.last_visual_summary = result.summary
        session.last_visual_summary_at = datetime.now(timezone.utc)
        session.last_scene_hash = frame.scene_hash
        session.cost_meter.mode = "focus" if frame.capture_reason in {"focus_roi", "screen_focus"} else "active"


def _normalized_hash_distance(a: str, b: str) -> float:
    if not a or not b:
        return 1.0
    length = min(len(a), len(b))
    distance = abs(len(a) - len(b))
    for index in range(length):
        if a[index] != b[index]:
            distance += 1
    return distance / max(len(a), len(b))


def _vision_model_name(settings: Settings) -> str:
    provider = settings.vision_provider.lower()
    if provider == "vertex_ai":
        return settings.vertex_ai_vision_model
    if provider == "gemini":
        return settings.gemini_vision_model
    if provider == "openai_compatible":
        return settings.openai_compatible_vision_model
    return provider
