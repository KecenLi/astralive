import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import get_settings
from app.contracts.events import EventEnvelope, make_event
from app.contracts.media import FramePayload
from app.core.session_state import SessionState
from app.providers.registry import ProviderRegistry
from app.services.avatar_service import AvatarService
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService
from app.services.wake_service import WakeService

logger = logging.getLogger(__name__)
router = APIRouter()
sessions: dict[str, SessionState] = {}


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    settings = get_settings()
    session = sessions.setdefault(session_id, SessionState(session_id=session_id, wake_word=settings.wake_word))
    registry = ProviderRegistry(settings)
    vision = VisionService(registry.vision(), settings)
    dialogue = DialogueService(registry.llm())
    avatar = AvatarService()
    wake = WakeService()

    send_lock = asyncio.Lock()
    response_task: asyncio.Task[None] | None = None

    await _send(websocket, make_event("server.session.ready", session_id, session.public_dict()), send_lock)
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
                    avatar,
                    wake,
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
        logger.info("websocket disconnected: %s", session_id)


async def _handle_event(
    websocket: WebSocket,
    event: EventEnvelope,
    session: SessionState,
    vision: VisionService,
    dialogue: DialogueService,
    avatar: AvatarService,
    wake: WakeService,
    started: float,
    send_lock: asyncio.Lock,
    response_task: asyncio.Task[None] | None,
) -> asyncio.Task[None] | None:
    if event.type == "client.debug.ping":
        await _send(websocket, make_event("debug.log", session.session_id, {"message": "pong"}), send_lock)
        return response_task

    if event.type == "client.wake.detected":
        _cancel_task(response_task)
        wake.wake(session)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, session.public_dict()),
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
        wake.sleep(session)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, session.public_dict()),
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
            make_event("server.session.state", session.session_id, session.public_dict()),
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

    if event.type in {"client.user.text", "client.user.speech.final"}:
        user_text = str(event.payload.get("text", "")).strip()
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
        elif dialogue.needs_vision(user_text) and not session.last_visual_summary:
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
            _run_dialogue_response(websocket, session, dialogue, avatar, user_text, started, send_lock)
        )
        task.add_done_callback(_log_task_exception)
        return task

    await _send_error(websocket, session.session_id, "unsupported_event", event.type, send_lock)
    return response_task


async def _run_dialogue_response(
    websocket: WebSocket,
    session: SessionState,
    dialogue: DialogueService,
    avatar: AvatarService,
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
            make_event("assistant.text.final", session.session_id, {"text": result.text}),
            send_lock,
        )
        await _send(
            websocket,
            avatar.state_event(session.session_id, "speaking", result.emotion, result.text, "talk", True),
            send_lock,
        )
        session.response_in_progress = False
        session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
        await _send(
            websocket,
            make_event("server.session.state", session.session_id, session.public_dict()),
            send_lock,
        )
        await _send_cost(websocket, session, send_lock)
    except asyncio.CancelledError:
        session.response_in_progress = False
        session.status = "listening"
        raise


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


def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task and not task.done():
        task.cancel()


def _log_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.exception("response task failed", exc_info=exc)
