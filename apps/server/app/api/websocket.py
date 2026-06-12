import asyncio
from contextlib import suppress
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import Settings
from app.config import get_settings
from app.contracts.events import EventEnvelope, make_event
from app.contracts.media import FramePayload
from app.contracts.model_io import AudioChunkPayload, TTSResult
from app.core.session_state import SessionState
from app.providers.registry import ProviderRegistry
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


class AudioRuntimeState:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.stream: RealtimeAudioStream | None = None
        self.receive_task: asyncio.Task[None] | None = None
        self.input_idle_task: asyncio.Task[None] | None = None
        self.turn_started_at: float = 0.0
        self.turn_bytes: int = 0
        self.input_finished: bool = False
        self.input_finished_at: float = 0.0


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    settings = get_settings()
    session = sessions.setdefault(session_id, SessionState(session_id=session_id, wake_word=settings.wake_word))
    registry = ProviderRegistry(settings)
    vision = VisionService(registry.vision(), settings)
    dialogue = DialogueService(registry.llm())
    audio = AudioService(registry.tts(), registry.asr(), settings, registry.realtime())
    avatar = AvatarService()
    wake = WakeService()

    send_lock = asyncio.Lock()
    response_task: asyncio.Task[None] | None = None
    audio_runtime = AudioRuntimeState()

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
                    started,
                    send_lock,
                    response_task,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("event handling failed")
                await _send_error(websocket, session_id, "event_failed", str(exc), send_lock)
    except WebSocketDisconnect:
        if response_task and not response_task.done():
            response_task.cancel()
        await _close_audio_runtime(audio_runtime)
        logger.info("websocket disconnected: %s", session_id)


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
        frame = FramePayload.model_validate(event.payload)
        result, from_cache = await vision.analyze_frame(
            session,
            frame,
            prompt=str(event.payload.get("prompt") or session.last_user_text or "请描述画面。"),
        )
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
        return response_task

    if event.type == "client.media.audio_chunk":
        payload = AudioChunkPayload.model_validate(event.payload)
        try:
            audio_bytes = audio.decode_audio_chunk(payload)
        except Exception as exc:  # noqa: BLE001
            await _send_error(websocket, session.session_id, "invalid_audio_chunk", str(exc), send_lock)
            return response_task
        session.cost_meter.bytes_uploaded += len(audio_bytes)
        if audio.has_realtime and audio.can_stream_realtime:
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
        if audio.has_realtime:
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

        asr_result = await audio.transcribe(turn_audio, _audio_metadata(payload))
        session.cost_meter.asr_calls += 1
        await _send(
            websocket,
            make_event(
                "asr.transcript.final",
                session.session_id,
                {"text": asr_result.text, "confidence": asr_result.confidence},
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

    if audio_runtime.stream is None:
        _cancel_task(response_task)
        audio_runtime.turn_started_at = started
        session.status = "listening"
        session.response_in_progress = True
        try:
            audio_runtime.stream = await audio.open_realtime_audio_stream(
                _realtime_metadata(session, payload)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to open realtime audio stream")
            await _close_audio_runtime(audio_runtime)
            await _send_error(websocket, session.session_id, "realtime_open_failed", str(exc), send_lock)
            await _send_cost(websocket, session, send_lock)
            return None
        audio_runtime.input_finished = False
        audio_runtime.input_finished_at = 0.0
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
    try:
        result = await dialogue.reply(session, user_text)
        session.status = "speaking"
        session.response_in_progress = True
        await _send(
            websocket,
            avatar.state_event(session.session_id, "thinking", result.emotion, "正在组织回答。"),
            send_lock,
        )
        async for chunk in dialogue.stream_text(result.text):
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
                {
                    "text": result.text,
                    "audio_expected": settings.tts_provider != "mock" and result.should_speak,
                },
            ),
            send_lock,
        )
        await _send(
            websocket,
            avatar.state_event(session.session_id, "speaking", result.emotion, result.text, "talk", True),
            send_lock,
        )
        if settings.tts_provider != "mock" and result.should_speak:
            try:
                tts_result = await audio.synthesize(result.text, result.emotion)
                session.cost_meter.tts_calls += 1
                await _send_tts_audio(
                    websocket,
                    session,
                    [tts_result],
                    "tts",
                    send_lock,
                    fallback_text=result.text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("tts synthesis failed")
                await _send_error(websocket, session.session_id, "tts_failed", str(exc), send_lock)
                await _send(
                    websocket,
                    make_event(
                        "assistant.audio.done",
                        session.session_id,
                        {"source": "tts", "chunks": 0, "fallback_text": result.text, "error": str(exc)},
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
                        avatar.state_event(session.session_id, "speaking", "neutral", "正在实时回应。", "talk", True),
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
        session.response_in_progress = False
        session.status = "listening"
        await _send_error(websocket, session.session_id, "realtime_stream_failed", str(exc), send_lock)
        await _send_cost(websocket, session, send_lock)
    finally:
        if audio_runtime.stream is stream:
            await stream.close()
            audio_runtime.stream = None
            audio_runtime.receive_task = None
            audio_runtime.turn_started_at = 0.0
            audio_runtime.turn_bytes = 0
            audio_runtime.input_finished = False
            audio_runtime.input_finished_at = 0.0


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
        result = await audio.respond_realtime_audio(audio_bytes, _realtime_metadata(session, payload))
        session.cost_meter.asr_calls += 1
        session.cost_meter.llm_calls += 1

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
    text: str,
    emotion: str,
    send_lock: asyncio.Lock,
) -> int:
    tts_text = _realtime_tts_fallback_text(text)
    try:
        tts_result = await audio.synthesize(tts_text, emotion)
        session.cost_meter.tts_calls += 1
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


async def _send_tts_audio(
    websocket: WebSocket,
    session: SessionState,
    chunks: list[TTSResult],
    source: str,
    send_lock: asyncio.Lock,
    fallback_text: str = "",
) -> int:
    sent = 0
    for index, chunk in enumerate(chunks):
        if not chunk.audio_base64:
            continue
        await _send(
            websocket,
            make_event("assistant.audio.chunk", session.session_id, _audio_event_payload(chunk, source, index)),
            send_lock,
        )
        sent += 1
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


async def _stream_text(text: str):
    for index in range(0, len(text), 12):
        await asyncio.sleep(0.02)
        yield text[index : index + 12]


async def _send(websocket: WebSocket, event: EventEnvelope, send_lock: asyncio.Lock) -> None:
    async with send_lock:
        await websocket.send_json(event.model_dump())


async def _send_cost(websocket: WebSocket, session: SessionState, send_lock: asyncio.Lock) -> None:
    await _send(
        websocket,
        make_event("cost.update", session.session_id, session.cost_meter.model_dump()),
        send_lock,
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


def _is_realtime_pcm(payload: AudioChunkPayload, settings: Settings) -> bool:
    normalized_mime = payload.mime.lower().replace(" ", "")
    return (
        payload.encoding == "pcm_s16le"
        and payload.channels == settings.audio_channels
        and payload.sample_rate == settings.audio_input_sample_rate
        and normalized_mime.startswith("audio/pcm")
        and f"rate={settings.audio_input_sample_rate}" in normalized_mime
    )


def _realtime_metadata(session: SessionState, payload: AudioChunkPayload) -> dict:
    metadata = _audio_metadata(payload)
    system_instruction = "你是 AstraLive，一个中文优先的实时视觉语音助手。回答要自然、简洁。"
    if session.last_visual_summary:
        system_instruction += f"\n当前视觉摘要：{session.last_visual_summary}"
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
        "server_realtime_audio": settings.realtime_provider != "none",
        "realtime_input_idle_timeout_seconds": settings.realtime_input_idle_timeout_seconds,
    }
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
    audio_runtime.stream = None
    audio_runtime.receive_task = None
    audio_runtime.input_idle_task = None
    audio_runtime.turn_started_at = 0.0
    audio_runtime.turn_bytes = 0
    audio_runtime.input_finished = False
    audio_runtime.input_finished_at = 0.0

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
                elapsed = time.perf_counter() - audio_runtime.input_finished_at
                remaining = settings.realtime_turn_timeout_seconds - elapsed
                if remaining <= 0:
                    raise TimeoutError("Gemini Live turn timed out while waiting for a streaming response.")
                timeout = min(timeout, remaining)
            done, _ = await asyncio.wait({next_task}, timeout=timeout)
            if done:
                return next_task.result()
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
