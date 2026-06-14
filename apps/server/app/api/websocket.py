import asyncio
from dataclasses import dataclass
from contextlib import suppress
import io
import logging
import time
from typing import Any
import wave

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import Settings
from app.config import get_settings
from app.contracts.events import EventEnvelope, make_event
from app.contracts.media import FramePayload
from app.contracts.model_io import AudioChunkPayload, TTSResult
from app.core.cost_estimator import CostEstimator
from app.core.session_state import SessionState
from app.providers.provider_container import get_provider_container
from app.providers.realtime.base import RealtimeAudioStream
from app.services.audio_service import AudioService
from app.services.avatar_service import AvatarService
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService
from app.services.wake_service import WakeService

logger = logging.getLogger(__name__)
router = APIRouter()
sessions: dict[str, SessionState] = {}
REALTIME_TTS_FALLBACK_MAX_CHARS = 360


@dataclass
class VisualFrameJob:
    sequence: int
    source: str
    frame: FramePayload
    prompt: str
    received_at: float


class AudioRuntimeState:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.stream_buffer = bytearray()
        self.last_audio_metadata: dict[str, Any] = {}
        self.stream: RealtimeAudioStream | None = None
        self.receive_task: asyncio.Task[None] | None = None
        self.input_idle_task: asyncio.Task[None] | None = None
        self.turn_started_at: float = 0.0
        self.turn_bytes: int = 0
        self.input_finished: bool = False
        self.input_finished_at: float = 0.0
        self.first_response_received: bool = False
        self.last_stream_event_at: float = 0.0


class VisualRuntimeState:
    def __init__(self) -> None:
        self.pending: dict[str, VisualFrameJob] = {}
        self.active_tasks: set[asyncio.Task[None]] = set()
        self.latest_sequence: int = 0
        self.latest_sequence_by_source: dict[str, int] = {}
        self.applied_sequence: int = 0
        self.dropped_pending_frames: int = 0
        self.provider_cooldown_until: float = 0.0
        self.provider_failure_count: int = 0
        self.provider_cooldown_notice_at: float = 0.0

    @property
    def task(self) -> asyncio.Task[None] | None:
        return next(iter(self.active_tasks), None)

    def enqueue(self, frame: FramePayload, prompt: str, settings: Settings) -> tuple[VisualFrameJob, int]:
        self.latest_sequence += 1
        source = _visual_source_key(frame.capture_reason)
        job = VisualFrameJob(
            sequence=self.latest_sequence,
            source=source,
            frame=frame,
            prompt=prompt,
            received_at=time.perf_counter(),
        )
        dropped = 1 if source in self.pending else 0
        self.pending[source] = job
        self.latest_sequence_by_source[source] = job.sequence

        pending_limit = max(1, settings.vision_pending_frame_limit)
        while len(self.pending) > pending_limit:
            oldest_source = min(self.pending, key=lambda item: self.pending[item].sequence)
            if oldest_source == source and len(self.pending) > 1:
                candidates = [item for item in self.pending if item != source]
                oldest_source = min(candidates, key=lambda item: self.pending[item].sequence)
            self.pending.pop(oldest_source, None)
            dropped += 1
        self.dropped_pending_frames += dropped
        return job, dropped


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    settings = get_settings()
    session = sessions.setdefault(session_id, SessionState(session_id=session_id, wake_word=settings.wake_word))
    container = get_provider_container(websocket.app)
    vision = container.vision_service()
    dialogue = container.dialogue_service()
    audio = container.audio_service()
    avatar = AvatarService()
    wake = WakeService()

    send_lock = asyncio.Lock()
    response_task: asyncio.Task[None] | None = None
    audio_runtime = AudioRuntimeState()
    visual_runtime = VisualRuntimeState()

    await _send(websocket, make_event("server.session.ready", session_id, _session_payload(session, settings)), send_lock)
    await _send_cost(websocket, session, send_lock)

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001
                await _send_error(websocket, session_id, "invalid_json", str(exc), send_lock)
                continue

            started = time.perf_counter()
            try:
                event = EventEnvelope.model_validate(raw)
            except ValidationError as exc:
                await _send_error(websocket, session_id, "invalid_event", exc.errors(), send_lock)
                continue

            if event.session_id != session_id:
                await _send_error(
                    websocket,
                    session_id,
                    "session_mismatch",
                    {"path_session_id": session_id, "event_session_id": event.session_id},
                    send_lock,
                )
                continue

            try:
                response_task = await _handle_event(
                    websocket,
                    event,
                    session,
                    vision,
                    dialogue,
                    audio,
                    avatar,
                    wake,
                    settings,
                    audio_runtime,
                    visual_runtime,
                    started,
                    send_lock,
                    response_task,
                )
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("event handling failed")
                await _send_error(websocket, session_id, "event_failed", str(exc), send_lock)
    except WebSocketDisconnect:
        if response_task and not response_task.done():
            response_task.cancel()
        await _close_audio_runtime(audio_runtime)
        await container.close_realtime_provider(audio.realtime_provider)
        _cancel_visual_runtime(visual_runtime)
        logger.info("websocket disconnected: %s", session_id)


async def _prewarm_audio(audio: AudioService, session_id: str) -> None:
    try:
        await audio.prewarm()
        logger.info("audio providers prewarmed: %s", session_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("audio provider prewarm failed: %s", session_id)


async def _handle_event(
    websocket: WebSocket,
    event: EventEnvelope,
    session: SessionState,
    vision: VisionService,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    wake: WakeService,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    visual_runtime: VisualRuntimeState,
    started: float,
    send_lock: asyncio.Lock,
    response_task: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    if event.type == "client.debug.ping":
        await _send(websocket, make_event("debug.log", session.session_id, {"message": "pong"}), send_lock)
        return response_task

    if event.type == "client.wake.detected":
        _cancel_task(response_task)
        await _close_audio_runtime(audio_runtime)
        _cancel_visual_runtime(visual_runtime)
        wake.wake(session)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send(
            websocket,
            avatar.state_event(session.session_id, "listening", "curious", "我在听。"),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return None

    if event.type == "client.wake.sleep":
        _cancel_task(response_task)
        await _close_audio_runtime(audio_runtime)
        _cancel_visual_runtime(visual_runtime)
        wake.sleep(session)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send(
            websocket,
            avatar.state_event(session.session_id, "sleeping", "sleepy", "进入睡眠。"),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return None

    if event.type in {"client.control.interrupt", "client.control.cancel_response"}:
        _cancel_task(response_task)
        await _close_audio_runtime(audio_runtime)
        _cancel_visual_runtime(visual_runtime)
        session.status = "interrupted"
        session.response_in_progress = False
        session.interrupted_count += 1
        await _send(
            websocket,
            avatar.state_event(session.session_id, "interrupted", "surprised", "我先停下。"),
            send_lock,
        )
        session.status = "listening"
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return None

    if event.type == "client.media.frame":
        if _should_defer_visual_frame(session, audio_runtime):
            visual_runtime.pending.clear()
            await _send(
                websocket,
                make_event(
                    "debug.log",
                    session.session_id,
                    {
                        "message": "Visual frame skipped while a voice response is in progress.",
                        "status": session.status,
                    },
                ),
                send_lock,
            )
            return response_task
        if _visual_provider_cooling_down(visual_runtime):
            visual_runtime.pending.clear()
            visual_runtime.dropped_pending_frames += 1
            now = time.perf_counter()
            if now - visual_runtime.provider_cooldown_notice_at > 10:
                visual_runtime.provider_cooldown_notice_at = now
                await _send(
                    websocket,
                    make_event(
                        "debug.log",
                        session.session_id,
                        {
                            "message": "Visual frame skipped while provider is cooling down.",
                            "remaining_seconds": round(visual_runtime.provider_cooldown_until - now, 1),
                        },
                    ),
                    send_lock,
                )
            return response_task
        frame = FramePayload.model_validate(event.payload)
        _, dropped = visual_runtime.enqueue(
            frame,
            str(event.payload.get("prompt") or session.last_user_text or "请描述画面。"),
            settings,
        )
        if dropped:
            await _send(
                websocket,
                make_event(
                    "debug.log",
                    session.session_id,
                    {
                        "message": "Older visual frame dropped; latest frame kept for analysis.",
                        "dropped": dropped,
                        "pending": len(visual_runtime.pending),
                        "active": len(visual_runtime.active_tasks),
                    },
                ),
                send_lock,
            )
        _start_visual_tasks(websocket, session, vision, settings, audio_runtime, visual_runtime, send_lock)
        return response_task

    if event.type == "client.media.audio_chunk":
        _cancel_visual_runtime(visual_runtime)
        payload = AudioChunkPayload.model_validate(event.payload)
        try:
            audio_bytes = audio.decode_audio_chunk(payload)
        except Exception as exc:  # noqa: BLE001
            await _send_error(websocket, session.session_id, "invalid_audio_chunk", str(exc), send_lock)
            return response_task
        session.cost_meter.bytes_uploaded += len(audio_bytes)
        if audio.has_realtime and audio.can_stream_realtime and not _prefer_asr_first(payload, settings):
            return await _handle_realtime_audio_chunk(
                websocket,
                session,
                audio,
                dialogue,
                avatar,
                settings,
                audio_runtime,
                payload,
                audio_bytes,
                started,
                send_lock,
                response_task,
            )

        audio_runtime.buffer.extend(audio_bytes)
        if len(audio_runtime.buffer) > settings.audio_turn_max_bytes:
            audio_runtime.buffer.clear()
            await _send_error(
                websocket,
                session.session_id,
                "audio_turn_too_large",
                f"Audio turn exceeds AUDIO_TURN_MAX_BYTES ({settings.audio_turn_max_bytes}).",
                send_lock,
            )
            await _send_cost(websocket, session, send_lock)
            return response_task
        if not payload.is_final:
            return response_task

        turn_audio = bytes(audio_runtime.buffer)
        audio_runtime.buffer.clear()
        if not turn_audio:
            await _send_error(websocket, session.session_id, "empty_audio", "Audio turn is empty.", send_lock)
            return response_task

        _cancel_task(response_task)
        if audio.has_realtime and not _prefer_asr_first(payload, settings):
            if not _is_realtime_pcm(payload, settings):
                await _send_error(
                    websocket,
                    session.session_id,
                    "unsupported_realtime_audio",
                    "Realtime audio requires mono PCM16 at AUDIO_INPUT_SAMPLE_RATE.",
                    send_lock,
                )
                await _send_cost(websocket, session, send_lock)
                return None
            task = asyncio.create_task(
                _run_realtime_audio_response(
                    websocket,
                    session,
                    audio,
                    avatar,
                    settings,
                    turn_audio,
                    payload,
                    started,
                    send_lock,
                )
            )
            task.add_done_callback(_log_task_exception)
            return task

        trace_id = _audio_trace_id(payload)
        await _send(
            websocket,
            avatar.state_event(session.session_id, "thinking", "curious", "正在识别语音。"),
            send_lock,
        )
        await _send(
            websocket,
            make_event(
                "debug.log",
                session.session_id,
                {
                    "message": "Audio turn using ASR-first route.",
                    "trace_id": trace_id,
                    "bytes": len(turn_audio),
                    "send_mode": payload.metadata.get("send_mode"),
                    "vad_provider": payload.metadata.get("vad_provider"),
                },
            ),
            send_lock,
        )
        asr_result = await audio.transcribe(turn_audio, _audio_metadata(payload))
        session.cost_meter.asr_calls += 1
        _record_estimated_cost(session, settings, raw=asr_result.raw, output_text=asr_result.text)
        await _send(
            websocket,
            make_event(
                "asr.transcript.final",
                session.session_id,
                {"text": asr_result.text, "confidence": asr_result.confidence, "trace_id": trace_id},
            ),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return await _handle_user_text(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            asr_result.text,
            started,
            send_lock,
            None,
        )

    if event.type in {"client.user.text", "client.user.speech.final"}:
        await _close_audio_runtime(audio_runtime)
        _cancel_visual_runtime(visual_runtime)
        user_text = str(event.payload.get("text", "")).strip()
        return await _handle_user_text(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            user_text,
            started,
            send_lock,
            response_task,
        )

    await _send_error(websocket, session.session_id, "unsupported_event", event.type, send_lock)
    return response_task


async def _handle_realtime_audio_chunk(
    websocket: WebSocket,
    session: SessionState,
    audio: AudioService,
    dialogue: DialogueService,
    avatar: AvatarService,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    payload: AudioChunkPayload,
    audio_bytes: bytes,
    started: float,
    send_lock: asyncio.Lock,
    response_task: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    if not _is_realtime_pcm(payload, settings):
        await _close_audio_runtime(audio_runtime)
        await _send_error(
            websocket,
            session.session_id,
            "unsupported_realtime_audio",
            "Realtime audio requires mono PCM16 at AUDIO_INPUT_SAMPLE_RATE.",
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return response_task

    if audio_runtime.stream is not None and audio_runtime.input_finished and not payload.is_final:
        await _close_audio_runtime(audio_runtime)

    if audio_runtime.stream is None and payload.is_final and not audio_bytes:
        await _send_error(websocket, session.session_id, "empty_audio", "Audio turn is empty.", send_lock)
        return response_task

    new_realtime_turn = audio_runtime.stream is None and audio_runtime.turn_bytes == 0
    if new_realtime_turn:
        audio_runtime.stream_buffer.clear()
        audio_runtime.last_audio_metadata = {}

    audio_runtime.turn_bytes += len(audio_bytes)
    if audio_runtime.turn_bytes > settings.audio_turn_max_bytes:
        await _close_audio_runtime(audio_runtime)
        await _send_error(
            websocket,
            session.session_id,
            "audio_turn_too_large",
            f"Audio turn exceeds AUDIO_TURN_MAX_BYTES ({settings.audio_turn_max_bytes}).",
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return None

    if audio_bytes:
        audio_runtime.stream_buffer.extend(audio_bytes)
    if audio_bytes or payload.is_final:
        audio_runtime.last_audio_metadata = _audio_metadata(payload)

    if audio_runtime.stream is None:
        _cancel_task(response_task)
        audio_runtime.turn_started_at = started
        session.status = "listening"
        session.response_in_progress = True
        try:
            audio_runtime.stream = await audio.open_realtime_audio_stream(
                _realtime_metadata(session, payload, settings)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to open realtime audio stream")
            await _close_audio_runtime(audio_runtime)
            await _send_error(websocket, session.session_id, "realtime_open_failed", str(exc), send_lock)
            await _send_cost(websocket, session, send_lock)
            return None
        audio_runtime.input_finished = False
        audio_runtime.input_finished_at = 0.0
        audio_runtime.first_response_received = False
        audio_runtime.last_stream_event_at = 0.0
        await _send(
            websocket,
            avatar.state_event(session.session_id, "listening", "curious", "正在接收实时语音。"),
            send_lock,
        )

    if audio_bytes:
        try:
            await audio_runtime.stream.send_audio(audio_bytes, payload.mime)
            if not payload.is_final:
                _arm_realtime_input_idle_timeout(websocket, session, settings, audio_runtime, send_lock)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to send realtime audio chunk")
            await _close_audio_runtime(audio_runtime)
            await _send_error(websocket, session.session_id, "realtime_send_failed", str(exc), send_lock)
            await _send_cost(websocket, session, send_lock)
            return None

    if payload.is_final:
        _cancel_realtime_input_idle_timeout(audio_runtime)
        try:
            await audio_runtime.stream.finish_audio()
            audio_runtime.input_finished = True
            audio_runtime.input_finished_at = time.perf_counter()
            audio_runtime.first_response_received = False
            audio_runtime.last_stream_event_at = 0.0
            if audio_runtime.receive_task is None:
                audio_runtime.receive_task = asyncio.create_task(
                    _run_realtime_stream_receiver(
                        websocket,
                        session,
                        dialogue,
                        audio,
                        avatar,
                        settings,
                        audio_runtime,
                        send_lock,
                    )
                )
                audio_runtime.receive_task.add_done_callback(_log_task_exception)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to finish realtime audio stream")
            await _close_audio_runtime(audio_runtime)
            await _send_error(websocket, session.session_id, "realtime_finish_failed", str(exc), send_lock)
            await _send_cost(websocket, session, send_lock)
            return None
    return audio_runtime.receive_task


async def _handle_user_text(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    user_text: str,
    started: float,
    send_lock: asyncio.Lock,
    response_task: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    if not user_text:
        await _send_error(websocket, session.session_id, "empty_text", "User text is empty.", send_lock)
        return response_task

    security_verdict = dialogue.assess_user_text(user_text)
    if not security_verdict.allowed:
        _cancel_task(response_task)
        task = asyncio.create_task(
            _run_dialogue_response(
                websocket,
                session,
                dialogue,
                audio,
                avatar,
                settings,
                user_text,
                started,
                send_lock,
            )
        )
        task.add_done_callback(_log_task_exception)
        return task

    if dialogue.needs_focus(user_text):
        session.cost_meter.mode = "focus"
        await _send(
            websocket,
            make_event(
                "vision.need_focus",
                session.session_id,
                {"reason": "focus_keyword", "text": user_text},
            ),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return response_task
    if dialogue.needs_vision(user_text) and not session.last_visual_summary:
        await _send(
            websocket,
            make_event(
                "vision.need_focus",
                session.session_id,
                {"reason": "missing_visual_summary", "text": user_text},
            ),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
        return response_task

    _cancel_task(response_task)
    task = asyncio.create_task(
        _run_dialogue_response(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            user_text,
            started,
            send_lock,
        )
    )
    task.add_done_callback(_log_task_exception)
    return task


async def _run_dialogue_response(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    user_text: str,
    started: float,
    send_lock: asyncio.Lock,
) -> None:
    tts_queue: asyncio.Queue[tuple[str, str] | None] | None = None
    tts_task: asyncio.Task[None] | None = None
    sent_audio_chunks = 0
    tts_error: str | None = None
    audio_done_sent = False
    final_text = ""
    audio_requested = False

    async def send_dialogue_audio_done(*, cancelled: bool = False, error: str | None = None) -> None:
        nonlocal audio_done_sent
        if audio_done_sent or not (audio_requested or sent_audio_chunks):
            return
        audio_done_sent = True
        payload = {
            "source": "tts",
            "chunks": sent_audio_chunks,
            **({"fallback_text": final_text} if sent_audio_chunks == 0 and final_text else {}),
            **({"cancelled": True} if cancelled else {}),
            **({"error": error} if error else {}),
        }
        with suppress(WebSocketDisconnect, RuntimeError):
            await _send(websocket, make_event("assistant.audio.done", session.session_id, payload), send_lock)

    async def run_tts_worker(queue: asyncio.Queue[tuple[str, str] | None]) -> None:
        nonlocal sent_audio_chunks, tts_error
        cost_estimator = CostEstimator.from_settings(settings)
        while True:
            item = await queue.get()
            if item is None:
                return
            segment_text, segment_emotion = item
            if tts_error:
                continue
            try:
                tts_result = await audio.synthesize(segment_text, segment_emotion)
                session.cost_meter.tts_calls += 1
                session.cost_meter.add_estimate(
                    cost_estimator.estimate(raw=tts_result.raw, input_text=segment_text)
                )
                sent_audio_chunks += await _send_tts_audio_chunks(
                    websocket,
                    session,
                    [tts_result],
                    "tts",
                    send_lock,
                    start_index=sent_audio_chunks,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                tts_error = str(exc)
                logger.exception("tts synthesis failed")
                await _send_error(websocket, session.session_id, "tts_failed", str(exc), send_lock)
                return

    try:
        session.status = "thinking"
        session.response_in_progress = True
        await _send(
            websocket,
            avatar.state_event(session.session_id, "thinking", "thinking", "正在组织回答。"),
            send_lock,
        )
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        if settings.tts_provider != "mock":
            tts_queue = asyncio.Queue()
            tts_task = asyncio.create_task(run_tts_worker(tts_queue))
            tts_task.add_done_callback(_log_task_exception)

        final_emotion = "neutral"
        saw_segment = False

        async for segment in dialogue.stream_reply(session, user_text):
            if not segment.text:
                continue
            final_text += segment.text
            final_emotion = segment.emotion
            if not saw_segment:
                saw_segment = True
                session.status = "speaking"
                await _send(
                    websocket,
                    avatar.state_event(
                        session.session_id,
                        "speaking",
                        final_emotion,
                        segment.text,
                        _motion_for_response_text(segment.text, final_emotion),
                        settings.tts_provider != "mock" and segment.should_speak,
                    ),
                    send_lock,
                )
            await _send(
                websocket,
                make_event("assistant.text.delta", session.session_id, {"delta": segment.text}),
                send_lock,
            )
            if tts_queue is not None and segment.should_speak:
                audio_requested = True
                await tts_queue.put((segment.text, final_emotion))

        await _send(
            websocket,
            make_event(
                "assistant.text.final",
                session.session_id,
                {
                    "text": final_text,
                    "audio_expected": audio_requested,
                },
            ),
            send_lock,
        )
        if saw_segment:
            await _send(
                websocket,
                avatar.state_event(
                    session.session_id,
                    "speaking",
                    final_emotion,
                    final_text,
                    _motion_for_response_text(final_text, final_emotion),
                    audio_requested,
                ),
                send_lock,
            )
        if tts_queue is not None:
            await tts_queue.put(None)
            if tts_task is not None:
                await tts_task
            if audio_requested:
                await send_dialogue_audio_done(error=tts_error)
        session.response_in_progress = False
        session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
    except asyncio.CancelledError:
        if tts_task and not tts_task.done():
            tts_task.cancel()
            with suppress(asyncio.CancelledError):
                await tts_task
        await send_dialogue_audio_done(cancelled=True)
        session.response_in_progress = False
        session.status = "listening"
        raise
    except Exception as exc:  # noqa: BLE001
        if tts_task and not tts_task.done():
            tts_task.cancel()
            with suppress(asyncio.CancelledError):
                await tts_task
        logger.exception("dialogue response failed")
        session.response_in_progress = False
        session.status = "listening"
        await _send_error(websocket, session.session_id, "dialogue_failed", str(exc), send_lock)
        await send_dialogue_audio_done(error=str(exc))
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)


async def _run_realtime_stream_receiver(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    send_lock: asyncio.Lock,
) -> None:
    stream = audio_runtime.stream
    if stream is None:
        return

    input_text = ""
    output_text = ""
    sent_audio_chunks = 0
    saw_model_activity = False
    started = audio_runtime.turn_started_at or time.perf_counter()

    try:
        iterator = stream.receive().__aiter__()
        while True:
            try:
                event = await _next_realtime_stream_event(iterator, audio_runtime, settings)
            except StopAsyncIteration:
                break
            if event.input_text:
                input_text += event.input_text
                await _send(
                    websocket,
                    make_event(
                        "asr.transcript.partial",
                        session.session_id,
                        {"text": input_text, "delta": event.input_text, "confidence": 0.72},
                    ),
                    send_lock,
                )

            if event.output_text:
                if not output_text:
                    session.status = "speaking"
                    await _send(
                        websocket,
                        avatar.state_event(
                            session.session_id,
                            "speaking",
                            "neutral",
                            "正在实时回应。",
                            _motion_for_response_text(event.output_text, "neutral"),
                            True,
                        ),
                        send_lock,
                    )
                output_text += event.output_text
                saw_model_activity = True
                await _send(
                    websocket,
                    make_event("assistant.text.delta", session.session_id, {"delta": event.output_text}),
                    send_lock,
                )

            for chunk in event.audio_chunks:
                if not chunk.audio_base64:
                    continue
                saw_model_activity = True
                await _send(
                    websocket,
                    make_event(
                        "assistant.audio.chunk",
                        session.session_id,
                        _audio_event_payload(chunk, "realtime", sent_audio_chunks),
                    ),
                    send_lock,
                )
                sent_audio_chunks += 1

            has_turn_output = bool(event.input_text or event.output_text or event.audio_chunks)
            has_accumulated_output = bool(input_text or output_text or sent_audio_chunks)
            if event.interrupted or (
                event.turn_complete and audio_runtime.input_finished and (has_turn_output or has_accumulated_output)
            ):
                break

        input_text = input_text.strip()
        output_text = output_text.strip()
        if input_text:
            session.last_user_text = input_text
            await _send(
                websocket,
                make_event(
                    "asr.transcript.final",
                    session.session_id,
                    {"text": input_text, "confidence": 0.75},
                ),
                send_lock,
            )
        if input_text and not output_text and sent_audio_chunks == 0:
            session.cost_meter.asr_calls += 1
            await _run_dialogue_response(
                websocket,
                session,
                dialogue,
                audio,
                avatar,
                settings,
                input_text,
                started,
                send_lock,
            )
            return
        fallback_audio_attempted = False
        if output_text:
            await _send(
                websocket,
                avatar.state_event(
                    session.session_id,
                    "speaking",
                    "neutral",
                    output_text,
                    _motion_for_response_text(output_text, "neutral"),
                    True,
                ),
                send_lock,
            )
            await _send(
                websocket,
                make_event(
                    "assistant.text.final",
                    session.session_id,
                    {
                        "text": output_text,
                        "audio_expected": sent_audio_chunks > 0 or settings.tts_provider != "mock",
                    },
                ),
                send_lock,
            )
            if sent_audio_chunks == 0 and settings.tts_provider != "mock":
                fallback_audio_attempted = True
                await _send_fallback_tts_audio(
                    websocket,
                    session,
                    audio,
                    settings,
                    output_text,
                    "neutral",
                    send_lock,
                )
        if sent_audio_chunks > 0 or not fallback_audio_attempted:
            await _send(
                websocket,
                make_event(
                    "assistant.audio.done",
                    session.session_id,
                    {"source": "realtime", "chunks": sent_audio_chunks},
                ),
                send_lock,
            )

        session.cost_meter.asr_calls += 1
        if saw_model_activity or output_text:
            session.cost_meter.llm_calls += 1
        if sent_audio_chunks:
            session.cost_meter.tts_calls += 1
        session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
        session.response_in_progress = False
        session.status = "listening"
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
    except asyncio.CancelledError:
        session.response_in_progress = False
        session.status = "listening"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("realtime stream receiver failed")
        fallback_audio = bytes(audio_runtime.stream_buffer)
        fallback_metadata = dict(audio_runtime.last_audio_metadata)
        recovered = await _recover_realtime_stream_failure(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            input_text,
            fallback_audio,
            fallback_metadata,
            exc,
            started,
            send_lock,
        )
        if not recovered:
            session.response_in_progress = False
            session.status = "listening"
            await _send_error(websocket, session.session_id, "realtime_stream_failed", str(exc), send_lock)
            await _send_cost(websocket, session, send_lock)
    finally:
        if audio_runtime.stream is stream:
            await stream.close()
            audio_runtime.stream = None
            audio_runtime.receive_task = None
            audio_runtime.stream_buffer.clear()
            audio_runtime.last_audio_metadata = {}
            audio_runtime.turn_started_at = 0.0
            audio_runtime.turn_bytes = 0
            audio_runtime.input_finished = False
            audio_runtime.input_finished_at = 0.0


async def _recover_realtime_stream_failure(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    input_text: str,
    fallback_audio: bytes,
    fallback_metadata: dict[str, Any],
    original_exc: Exception,
    started: float,
    send_lock: asyncio.Lock,
) -> bool:
    transcript = input_text.strip()
    if transcript:
        session.cost_meter.asr_calls += 1
        session.last_user_text = transcript
        await _send(
            websocket,
            make_event(
                "asr.transcript.final",
                session.session_id,
                {"text": transcript, "confidence": 0.55, "recovered_from": "realtime_stream"},
            ),
            send_lock,
        )
        await _run_recovered_dialogue_response(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            transcript,
            started,
            send_lock,
        )
        return True

    if not fallback_audio:
        await _send_realtime_failure_notice(
            websocket,
            session,
            audio,
            avatar,
            settings,
            started,
            send_lock,
            "我这边听到实时语音通道断开了，但没有收到可识别的音频。请再说一次。",
            original_exc,
        )
        return True

    await _send(
        websocket,
        avatar.state_event(session.session_id, "thinking", "concerned", "实时语音无响应，正在改用普通识别。"),
        send_lock,
    )
    try:
        asr_audio, asr_metadata = _fallback_asr_payload(fallback_audio, fallback_metadata, settings)
        asr_result = await asyncio.wait_for(
            audio.transcribe(asr_audio, asr_metadata),
            timeout=settings.realtime_recovery_asr_timeout_seconds,
        )
        session.cost_meter.asr_calls += 1
        _record_estimated_cost(session, settings, raw=asr_result.raw, output_text=asr_result.text)
    except asyncio.TimeoutError as exc:
        logger.exception("realtime fallback ASR timed out")
        await _send_realtime_failure_notice(
            websocket,
            session,
            audio,
            avatar,
            settings,
            started,
            send_lock,
            "我听到你说话了，但备用识别超时了。请再说一次，或者先用文本输入。",
            exc,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("realtime fallback ASR failed")
        await _send_realtime_failure_notice(
            websocket,
            session,
            audio,
            avatar,
            settings,
            started,
            send_lock,
            "我听到你说话了，但实时通道和备用识别都没有返回结果。请再说一次，或者先用文本输入。",
            exc,
        )
        return True

    transcript = asr_result.text.strip()
    if not transcript:
        await _send_realtime_failure_notice(
            websocket,
            session,
            audio,
            avatar,
            settings,
            started,
            send_lock,
            "我听到你说话了，但这次没有识别出清楚内容。请离麦克风近一点再说一次。",
            original_exc,
        )
        return True

    session.last_user_text = transcript
    await _send(
        websocket,
        make_event(
            "asr.transcript.final",
            session.session_id,
            {
                "text": transcript,
                "confidence": asr_result.confidence,
                "recovered_from": "realtime_stream",
            },
        ),
        send_lock,
    )
    await _send_cost(websocket, session, send_lock)
    await _run_recovered_dialogue_response(
        websocket,
        session,
        dialogue,
        audio,
        avatar,
        settings,
        transcript,
        started,
        send_lock,
    )
    return True


async def _run_recovered_dialogue_response(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    user_text: str,
    started: float,
    send_lock: asyncio.Lock,
) -> None:
    try:
        await _run_dialogue_response(
            websocket,
            session,
            dialogue,
            audio,
            avatar,
            settings,
            user_text,
            started,
            send_lock,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("realtime fallback dialogue failed")
        await _send_realtime_failure_notice(
            websocket,
            session,
            audio,
            avatar,
            settings,
            started,
            send_lock,
            "我识别到了你的话，但生成回复时失败了。请稍后再试，或者先切换到文本输入。",
            exc,
        )


async def _send_realtime_failure_notice(
    websocket: WebSocket,
    session: SessionState,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    started: float,
    send_lock: asyncio.Lock,
    message: str,
    exc: Exception,
) -> None:
    session.response_in_progress = False
    session.status = "listening"
    session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
    await _send(
        websocket,
        make_event(
            "debug.log",
            session.session_id,
            {"message": "Realtime voice recovery failed.", "detail": str(exc)},
        ),
        send_lock,
    )
    await _send(
        websocket,
        make_event(
            "assistant.text.final",
            session.session_id,
            {"text": message, "audio_expected": settings.tts_provider != "mock"},
        ),
        send_lock,
    )
    if settings.tts_provider != "mock":
        try:
            tts_result = await audio.synthesize(message, "concerned")
            session.cost_meter.tts_calls += 1
            await _send_tts_audio(websocket, session, [tts_result], "notice", send_lock, fallback_text=message)
        except Exception as tts_exc:  # noqa: BLE001
            logger.exception("fixed notice tts failed")
            await _send(
                websocket,
                make_event(
                    "assistant.audio.done",
                    session.session_id,
                    {"source": "notice", "chunks": 0, "fallback_text": message, "error": str(tts_exc)},
                ),
                send_lock,
            )
    else:
        await _send(
            websocket,
            make_event(
                "assistant.audio.done",
                session.session_id,
                {"source": "notice", "chunks": 0, "fallback_text": message},
            ),
            send_lock,
        )
    await _send(
        websocket,
        avatar.state_event(session.session_id, "listening", "concerned", message),
        send_lock,
    )
    await _send(
        websocket,
        make_event("server.session.state", session.session_id, _session_payload(session, settings)),
        send_lock,
    )
    await _send_cost(websocket, session, send_lock)


def _fallback_asr_payload(
    audio_bytes: bytes,
    metadata: dict[str, Any],
    settings: Settings,
) -> tuple[bytes, dict[str, Any]]:
    asr_metadata = dict(metadata)
    if str(asr_metadata.get("encoding") or "").lower() != "pcm_s16le":
        return audio_bytes, asr_metadata

    sample_rate = int(asr_metadata.get("sample_rate") or settings.audio_input_sample_rate)
    channels = int(asr_metadata.get("channels") or settings.audio_channels)
    asr_metadata["mime"] = "audio/wav"
    asr_metadata["encoding"] = "wav"
    return _pcm16_to_wav(audio_bytes, sample_rate, channels), asr_metadata


def _pcm16_to_wav(audio_bytes: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)
    return buffer.getvalue()


def _should_defer_visual_frame(session: SessionState, audio_runtime: AudioRuntimeState) -> bool:
    return (
        session.response_in_progress
        or session.status in {"thinking", "speaking"}
        or audio_runtime.stream is not None
        or bool(audio_runtime.receive_task and not audio_runtime.receive_task.done())
    )


def _visual_source_key(capture_reason: str) -> str:
    if capture_reason.startswith("screen_") or capture_reason == "scene_changed":
        return "screen"
    if capture_reason.startswith("camera_"):
        return "camera"
    if capture_reason in {"focus_roi", "visual_question"}:
        return "focus"
    return "general"


def _start_visual_tasks(
    websocket: WebSocket,
    session: SessionState,
    vision: VisionService,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    visual_runtime: VisualRuntimeState,
    send_lock: asyncio.Lock,
) -> None:
    if _should_defer_visual_frame(session, audio_runtime):
        return
    if _visual_provider_cooling_down(visual_runtime):
        visual_runtime.dropped_pending_frames += len(visual_runtime.pending)
        visual_runtime.pending.clear()
        return

    max_concurrency = max(1, settings.vision_max_concurrency)
    while visual_runtime.pending and len(visual_runtime.active_tasks) < max_concurrency:
        source = max(visual_runtime.pending, key=lambda item: visual_runtime.pending[item].sequence)
        job = visual_runtime.pending.pop(source)
        task = asyncio.create_task(
            _run_visual_frame_analysis(
                websocket,
                session,
                vision,
                settings,
                audio_runtime,
                visual_runtime,
                job,
                send_lock,
            )
        )
        visual_runtime.active_tasks.add(task)
        task.add_done_callback(_log_task_exception)


async def _run_visual_frame_analysis(
    websocket: WebSocket,
    session: SessionState,
    vision: VisionService,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    visual_runtime: VisualRuntimeState,
    job: VisualFrameJob,
    send_lock: asyncio.Lock,
) -> None:
    frame = job.frame
    try:
        result, from_cache = await vision.analyze_frame(session, frame, prompt=job.prompt, commit=False)
        if _vision_result_failed(result):
            cooldown_seconds = _mark_visual_provider_failure(visual_runtime, result)
            await _send(
                websocket,
                make_event(
                    "debug.log",
                    session.session_id,
                    {
                        "message": "Visual provider failed; cooling down to protect voice response latency.",
                        "frame_id": frame.frame_id,
                        "source": job.source,
                        "cooldown_seconds": round(cooldown_seconds, 1),
                        "failure_count": visual_runtime.provider_failure_count,
                        "detail": str(result.raw.get("error", ""))[:240],
                    },
                ),
                send_lock,
            )
            await _send_cost(websocket, session, send_lock)
            return
        visual_runtime.provider_failure_count = 0
        visual_runtime.provider_cooldown_until = 0.0
        result_age = time.perf_counter() - job.received_at
        latest_for_source = visual_runtime.latest_sequence_by_source.get(job.source, job.sequence)
        if (
            job.sequence < latest_for_source
            or job.sequence < visual_runtime.applied_sequence
            or result_age > settings.vision_result_max_age_seconds
        ):
            await _send(
                websocket,
                make_event(
                    "debug.log",
                    session.session_id,
                    {
                        "message": "Stale visual result discarded.",
                        "frame_id": frame.frame_id,
                        "source": job.source,
                        "sequence": job.sequence,
                        "latest_sequence": latest_for_source,
                        "applied_sequence": visual_runtime.applied_sequence,
                        "age_seconds": round(result_age, 3),
                    },
                ),
                send_lock,
            )
            await _send_cost(websocket, session, send_lock)
            return

        vision.apply_frame_result(session, frame, result)
        visual_runtime.applied_sequence = max(visual_runtime.applied_sequence, job.sequence)
        if _should_defer_visual_frame(session, audio_runtime):
            await _send(
                websocket,
                make_event(
                    "debug.log",
                    session.session_id,
                    {
                        "message": "Visual summary retained but UI update deferred because voice is active.",
                        "frame_id": frame.frame_id,
                        "status": session.status,
                    },
                ),
                send_lock,
            )
            await _send_cost(websocket, session, send_lock)
            return

        await _send(
            websocket,
            make_event(
                "vision.summary",
                session.session_id,
                {
                    "summary_id": f"vis_{int(time.time() * 1000)}",
                    "frame_id": frame.frame_id,
                    "summary": result.summary,
                    "objects": [obj.model_dump() for obj in result.objects],
                    "ocr_text": result.ocr_text,
                    "confidence": result.confidence,
                    "from_cache": from_cache,
                },
            ),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("visual frame analysis failed")
        await _send_error(websocket, session.session_id, "vision_error", str(exc), send_lock)
    finally:
        current_task = asyncio.current_task()
        if current_task:
            visual_runtime.active_tasks.discard(current_task)
        _start_visual_tasks(websocket, session, vision, settings, audio_runtime, visual_runtime, send_lock)


def _vision_result_failed(result: Any) -> bool:
    raw = getattr(result, "raw", None)
    return isinstance(raw, dict) and bool(raw.get("error"))


def _mark_visual_provider_failure(visual_runtime: VisualRuntimeState, result: Any) -> float:
    visual_runtime.provider_failure_count += 1
    detail = ""
    raw = getattr(result, "raw", None)
    if isinstance(raw, dict):
        detail = str(raw.get("error", ""))
    cooldown_seconds = _visual_provider_cooldown_seconds(detail, visual_runtime.provider_failure_count)
    visual_runtime.provider_cooldown_until = time.perf_counter() + cooldown_seconds
    return cooldown_seconds


def _visual_provider_cooling_down(visual_runtime: VisualRuntimeState) -> bool:
    return visual_runtime.provider_cooldown_until > time.perf_counter()


def _visual_provider_cooldown_seconds(detail: str, failure_count: int) -> float:
    lowered = detail.lower()
    if (
        "429" in lowered
        or "resource_exhausted" in lowered
        or "resource exhausted" in lowered
        or "quota" in lowered
        or "rate limit" in lowered
    ):
        return min(300.0, 90.0 * max(1, failure_count))
    if "timeout" in lowered or "timed out" in lowered:
        return min(30.0, 8.0 * max(1, failure_count))
    return min(30.0, 4.0 * (2 ** min(max(0, failure_count - 1), 3)))


def _cancel_visual_runtime(visual_runtime: VisualRuntimeState) -> None:
    visual_runtime.pending.clear()
    tasks = list(visual_runtime.active_tasks)
    visual_runtime.active_tasks.clear()
    for task in tasks:
        if not task.done():
            task.cancel()


async def _run_realtime_audio_response(
    websocket: WebSocket,
    session: SessionState,
    audio: AudioService,
    avatar: AvatarService,
    settings: Settings,
    audio_bytes: bytes,
    payload: AudioChunkPayload,
    started: float,
    send_lock: asyncio.Lock,
) -> None:
    try:
        session.status = "thinking"
        session.response_in_progress = True
        await _send(
            websocket,
            avatar.state_event(session.session_id, "thinking", "curious", "正在听取语音。"),
            send_lock,
        )
        result = await audio.respond_realtime_audio(audio_bytes, _realtime_metadata(session, payload, settings))
        session.cost_meter.asr_calls += 1
        session.cost_meter.llm_calls += 1
        _record_estimated_cost(
            session,
            settings,
            raw=result.raw,
            input_text=result.input_text,
            output_text=result.output_text,
        )

        if result.input_text:
            session.last_user_text = result.input_text
            await _send(
                websocket,
                make_event(
                    "asr.transcript.final",
                    session.session_id,
                    {"text": result.input_text, "confidence": 0.75},
                ),
                send_lock,
            )

        audio_expected = any(chunk.audio_base64 for chunk in result.audio_chunks) or (
            bool(result.output_text) and settings.tts_provider != "mock"
        )
        if result.output_text:
            session.status = "speaking"
            async for chunk in _stream_text(result.output_text):
                await _send(
                    websocket,
                    make_event("assistant.text.delta", session.session_id, {"delta": chunk}),
                    send_lock,
                )
            await _send(
                websocket,
                make_event(
                    "assistant.text.final",
                    session.session_id,
                    {"text": result.output_text, "audio_expected": audio_expected},
                ),
                send_lock,
            )

        sent_chunks = 0
        used_fallback_tts = False
        if any(chunk.audio_base64 for chunk in result.audio_chunks):
            sent_chunks = await _send_tts_audio(websocket, session, result.audio_chunks, "realtime", send_lock)
        elif result.output_text and settings.tts_provider != "mock":
            used_fallback_tts = True
            sent_chunks = await _send_fallback_tts_audio(
                websocket,
                session,
                audio,
                settings,
                result.output_text,
                result.emotion,
                send_lock,
            )
        else:
            await _send_tts_audio(websocket, session, [], "realtime", send_lock)
        if sent_chunks and not used_fallback_tts:
            session.cost_meter.tts_calls += 1
        await _send(
            websocket,
            avatar.state_event(
                session.session_id,
                "speaking",
                result.emotion,
                result.output_text or "Live 音频回复。",
                "talk",
                bool(sent_chunks),
            ),
            send_lock,
        )
        session.response_in_progress = False
        session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, _session_payload(session, settings)),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
    except asyncio.CancelledError:
        session.response_in_progress = False
        session.status = "listening"
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("realtime response failed")
        session.response_in_progress = False
        session.status = "listening"
        await _send_error(websocket, session.session_id, "realtime_failed", str(exc), send_lock)
        await _send_cost(websocket, session, send_lock)


async def _send_fallback_tts_audio(
    websocket: WebSocket,
    session: SessionState,
    audio: AudioService,
    settings: Settings,
    text: str,
    emotion: str,
    send_lock: asyncio.Lock,
) -> int:
    tts_text = _realtime_tts_fallback_text(text)
    try:
        tts_result = await audio.synthesize(tts_text, emotion)
        session.cost_meter.tts_calls += 1
        _record_estimated_cost(session, settings, raw=tts_result.raw, input_text=tts_text)
        return await _send_tts_audio(websocket, session, [tts_result], "tts", send_lock, fallback_text=tts_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("realtime tts fallback failed")
        await _send_error(websocket, session.session_id, "tts_failed", str(exc), send_lock)
        await _send(
            websocket,
            make_event(
                "assistant.audio.done",
                session.session_id,
                {"source": "tts", "chunks": 0, "fallback_text": tts_text, "error": str(exc)},
            ),
            send_lock,
        )
        return 0


def _realtime_tts_fallback_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= REALTIME_TTS_FALLBACK_MAX_CHARS:
        return normalized
    return normalized[:REALTIME_TTS_FALLBACK_MAX_CHARS].rstrip() + "..."


def _motion_for_response_text(text: str, emotion: str) -> str:
    normalized = text.lower()
    if emotion in {"happy"} or any(
        keyword in normalized
        for keyword in ("完成", "好了", "可以", "没问题", "收到", "当然", "ok", "done", "great")
    ):
        return "happy"
    if emotion in {"concerned", "confused"} or any(
        keyword in normalized
        for keyword in ("抱歉", "失败", "错误", "超时", "不确定", "听不清", "无法", "不能")
    ):
        return "concerned"
    if emotion == "surprised" or any(keyword in normalized for keyword in ("注意", "等等", "危险", "小心")):
        return "surprised"
    if emotion in {"curious", "thinking"} or any(
        marker in normalized for marker in ("?", "？", "吗", "呢", "为什么", "怎么", "如何")
    ):
        return "curious"
    return "talk"


async def _send_tts_audio(
    websocket: WebSocket,
    session: SessionState,
    chunks: list[TTSResult],
    source: str,
    send_lock: asyncio.Lock,
    fallback_text: str = "",
) -> int:
    sent = await _send_tts_audio_chunks(websocket, session, chunks, source, send_lock)
    await _send(
        websocket,
        make_event(
            "assistant.audio.done",
            session.session_id,
            {
                "source": source,
                "chunks": sent,
                **({"fallback_text": fallback_text} if sent == 0 and fallback_text else {}),
            },
        ),
        send_lock,
    )
    return sent


async def _send_tts_audio_chunks(
    websocket: WebSocket,
    session: SessionState,
    chunks: list[TTSResult],
    source: str,
    send_lock: asyncio.Lock,
    *,
    start_index: int = 0,
) -> int:
    sent = 0
    for index, chunk in enumerate(chunks, start=start_index):
        if not chunk.audio_base64:
            continue
        await _send(
            websocket,
            make_event("assistant.audio.chunk", session.session_id, _audio_event_payload(chunk, source, index)),
            send_lock,
        )
        sent += 1
    return sent


async def _stream_text(text: str):
    for index in range(0, len(text), 12):
        await asyncio.sleep(0.02)
        yield text[index : index + 12]


async def _send(websocket: WebSocket, event: EventEnvelope, send_lock: asyncio.Lock) -> None:
    async with send_lock:
        try:
            await websocket.send_json(event.model_dump())
        except WebSocketDisconnect:
            raise
        except RuntimeError as exc:
            if "close message has been sent" in str(exc) or "WebSocket is not connected" in str(exc):
                raise WebSocketDisconnect from exc
            raise


async def _send_cost(websocket: WebSocket, session: SessionState, send_lock: asyncio.Lock) -> None:
    await _send(
        websocket,
        make_event("cost.update", session.session_id, session.cost_meter.model_dump()),
        send_lock,
    )


def _record_estimated_cost(
    session: SessionState,
    settings: Settings,
    *,
    raw: Any = None,
    input_text: Any = None,
    output_text: Any = None,
) -> None:
    session.cost_meter.add_estimate(
        CostEstimator.from_settings(settings).estimate(
            raw=raw,
            input_text=input_text,
            output_text=output_text,
        )
    )


async def _send_error(
    websocket: WebSocket,
    session_id: str,
    code: str,
    detail: Any,
    send_lock: asyncio.Lock,
) -> None:
    await _send(websocket, make_event("error", session_id, {"code": code, "detail": detail}), send_lock)


def _audio_metadata(payload: AudioChunkPayload) -> dict:
    return payload.model_dump(exclude={"data_base64"})


def _audio_trace_id(payload: AudioChunkPayload) -> str:
    trace_id = payload.metadata.get("trace_id")
    return str(trace_id) if trace_id else ""


def _prefer_asr_first(payload: AudioChunkPayload, settings: Settings) -> bool:
    route = str(payload.metadata.get("route") or settings.audio_route or "asr_first").lower()
    return route != "live_first"


def _is_realtime_pcm(payload: AudioChunkPayload, settings: Settings) -> bool:
    normalized_mime = payload.mime.lower().replace(" ", "")
    return (
        payload.encoding == "pcm_s16le"
        and payload.channels == settings.audio_channels
        and payload.sample_rate == settings.audio_input_sample_rate
        and normalized_mime.startswith("audio/pcm")
        and f"rate={settings.audio_input_sample_rate}" in normalized_mime
    )


def _realtime_metadata(session: SessionState, payload: AudioChunkPayload, settings: Settings) -> dict:
    metadata = _audio_metadata(payload)
    system_instruction = settings.persona_prompt
    if session.last_visual_summary:
        system_instruction += f"\n当前视觉摘要：{session.last_visual_summary}"
    system_instruction += "\n输出约束：只输出要说给用户听的话；不要输出 Markdown；不要解释内部流程。"
    metadata["system_instruction"] = system_instruction
    return metadata


def _audio_event_payload(chunk: TTSResult, source: str, index: int) -> dict:
    return {
        "chunk_id": f"{source}_{int(time.time() * 1000)}_{index}",
        "source": source,
        "mime": chunk.mime,
        "sample_rate": chunk.sample_rate,
        "channels": chunk.channels,
        "encoding": chunk.encoding,
        "duration_ms": chunk.duration_ms,
        "data_base64": chunk.audio_base64,
        "is_final": False,
    }


def _session_payload(session: SessionState, settings: Settings) -> dict:
    payload = session.public_dict()
    payload["audio"] = {
        "asr_provider": settings.asr_provider,
        "tts_provider": settings.tts_provider,
        "realtime_provider": settings.realtime_provider,
        "input_sample_rate": settings.audio_input_sample_rate,
        "output_sample_rate": settings.audio_output_sample_rate,
        "channels": settings.audio_channels,
        "server_tts": settings.tts_provider != "mock",
        "server_realtime_audio": settings.realtime_provider != "none" or settings.asr_provider != "mock",
        "realtime_input_idle_timeout_seconds": settings.realtime_input_idle_timeout_seconds,
        "realtime_first_response_timeout_seconds": settings.realtime_first_response_timeout_seconds,
        "realtime_stream_gap_timeout_seconds": settings.realtime_stream_gap_timeout_seconds,
        "realtime_turn_max_seconds": settings.realtime_turn_max_seconds,
    }
    payload["visual"] = {"scene_change_threshold": settings.scene_change_threshold}
    return payload


def _arm_realtime_input_idle_timeout(
    websocket: WebSocket,
    session: SessionState,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    send_lock: asyncio.Lock,
) -> None:
    _cancel_realtime_input_idle_timeout(audio_runtime)
    if settings.realtime_input_idle_timeout_seconds <= 0:
        return
    audio_runtime.input_idle_task = asyncio.create_task(
        _run_realtime_input_idle_timeout(websocket, session, settings, audio_runtime, send_lock)
    )
    audio_runtime.input_idle_task.add_done_callback(_log_task_exception)


def _cancel_realtime_input_idle_timeout(audio_runtime: AudioRuntimeState) -> None:
    task = audio_runtime.input_idle_task
    audio_runtime.input_idle_task = None
    if task and task is not asyncio.current_task() and not task.done():
        task.cancel()


async def _run_realtime_input_idle_timeout(
    websocket: WebSocket,
    session: SessionState,
    settings: Settings,
    audio_runtime: AudioRuntimeState,
    send_lock: asyncio.Lock,
) -> None:
    await asyncio.sleep(settings.realtime_input_idle_timeout_seconds)
    if audio_runtime.stream is None or audio_runtime.input_finished:
        return

    await _close_audio_runtime(audio_runtime)
    session.response_in_progress = False
    session.status = "listening"
    await _send_error(
        websocket,
        session.session_id,
        "realtime_input_idle_timeout",
        f"No realtime audio chunk or final received for {settings.realtime_input_idle_timeout_seconds:g} seconds.",
        send_lock,
    )
    await _send(
        websocket,
        make_event("server.session.state", session.session_id, _session_payload(session, settings)),
        send_lock,
    )
    await _send_cost(websocket, session, send_lock)


async def _close_audio_runtime(audio_runtime: AudioRuntimeState) -> None:
    current_task = asyncio.current_task()
    input_idle_task = audio_runtime.input_idle_task
    receive_task = audio_runtime.receive_task
    stream = audio_runtime.stream

    audio_runtime.buffer.clear()
    audio_runtime.stream_buffer.clear()
    audio_runtime.last_audio_metadata = {}
    audio_runtime.stream = None
    audio_runtime.receive_task = None
    audio_runtime.input_idle_task = None
    audio_runtime.turn_started_at = 0.0
    audio_runtime.turn_bytes = 0
    audio_runtime.input_finished = False
    audio_runtime.input_finished_at = 0.0
    audio_runtime.first_response_received = False
    audio_runtime.last_stream_event_at = 0.0

    if input_idle_task and input_idle_task is not current_task and not input_idle_task.done():
        input_idle_task.cancel()
        try:
            await input_idle_task
        except asyncio.CancelledError:
            pass
    if receive_task and receive_task is not current_task and not receive_task.done():
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
    if stream:
        await stream.close()


async def _next_realtime_stream_event(
    iterator: Any,
    audio_runtime: AudioRuntimeState,
    settings: Settings,
) -> Any:
    next_task = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            timeout = 0.25
            if audio_runtime.input_finished_at:
                now = time.perf_counter()
                turn_remaining = settings.realtime_turn_max_seconds - (now - audio_runtime.input_finished_at)
                if turn_remaining <= 0:
                    raise TimeoutError("Gemini Live turn exceeded maximum streaming duration.")

                if audio_runtime.first_response_received:
                    anchor = audio_runtime.last_stream_event_at or audio_runtime.input_finished_at
                    phase_remaining = settings.realtime_stream_gap_timeout_seconds - (now - anchor)
                    phase_name = "stream gap"
                else:
                    phase_remaining = settings.realtime_first_response_timeout_seconds - (
                        now - audio_runtime.input_finished_at
                    )
                    phase_name = "first response"

                if phase_remaining <= 0:
                    raise TimeoutError(f"Gemini Live {phase_name} timed out while waiting for a streaming response.")
                timeout = min(timeout, turn_remaining, phase_remaining)
            done, _ = await asyncio.wait({next_task}, timeout=timeout)
            if done:
                event = next_task.result()
                audio_runtime.first_response_received = True
                audio_runtime.last_stream_event_at = time.perf_counter()
                return event
    except BaseException:
        if not next_task.done():
            next_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await next_task
        raise


def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task and not task.done():
        task.cancel()


def _log_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.exception("response task failed", exc_info=exc)
