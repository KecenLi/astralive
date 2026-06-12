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

    await _send(websocket, make_event("server.session.ready", session_id, session.public_dict()))
    await _send_cost(websocket, session)

    try:
        while True:
            raw = await websocket.receive_json()
            started = time.perf_counter()
            try:
                event = EventEnvelope.model_validate(raw)
            except ValidationError as exc:
                await _send_error(websocket, session_id, "invalid_event", exc.errors())
                continue

            try:
                await _handle_event(
                    websocket,
                    event,
                    session,
                    vision,
                    dialogue,
                    avatar,
                    wake,
                    started,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("event handling failed")
                await _send_error(websocket, session_id, "event_failed", str(exc))
    except WebSocketDisconnect:
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
) -> None:
    if event.type == "client.debug.ping":
        await _send(websocket, make_event("debug.log", session.session_id, {"message": "pong"}))
        return

    if event.type == "client.wake.detected":
        wake.wake(session)
        await _send(websocket, make_event("server.session.state", session.session_id, session.public_dict()))
        await _send(websocket, avatar.state_event(session.session_id, "listening", "curious", "我在听。"))
        await _send_cost(websocket, session)
        return

    if event.type == "client.wake.sleep":
        wake.sleep(session)
        await _send(websocket, make_event("server.session.state", session.session_id, session.public_dict()))
        await _send(websocket, avatar.state_event(session.session_id, "sleeping", "sleepy", "进入睡眠。"))
        await _send_cost(websocket, session)
        return

    if event.type == "client.control.interrupt":
        session.status = "interrupted"
        session.response_in_progress = False
        session.interrupted_count += 1
        await _send(websocket, avatar.state_event(session.session_id, "interrupted", "surprised", "我先停下。"))
        session.status = "listening"
        await _send(websocket, make_event("server.session.state", session.session_id, session.public_dict()))
        await _send_cost(websocket, session)
        return

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
        )
        await _send_cost(websocket, session)
        return

    if event.type in {"client.user.text", "client.user.speech.final"}:
        user_text = str(event.payload.get("text", "")).strip()
        if not user_text:
            await _send_error(websocket, session.session_id, "empty_text", "User text is empty.")
            return
        if dialogue.needs_focus(user_text):
            session.cost_meter.mode = "focus"
            await _send(
                websocket,
                make_event(
                    "vision.need_focus",
                    session.session_id,
                    {"reason": "focus_keyword", "text": user_text},
                ),
            )
        elif dialogue.needs_vision(user_text) and not session.last_visual_summary:
            await _send(
                websocket,
                make_event(
                    "vision.need_focus",
                    session.session_id,
                    {"reason": "missing_visual_summary", "text": user_text},
                ),
            )

        result = await dialogue.reply(session, user_text)
        session.status = "speaking"
        session.response_in_progress = True
        await _send(websocket, avatar.state_event(session.session_id, "thinking", result.emotion, "正在组织回答。"))
        async for chunk in dialogue.stream_text(result.text):
            await _send(websocket, make_event("assistant.text.delta", session.session_id, {"delta": chunk}))
        await _send(websocket, make_event("assistant.text.final", session.session_id, {"text": result.text}))
        await _send(
            websocket,
            avatar.state_event(session.session_id, "speaking", result.emotion, result.text, "talk", True),
        )
        session.response_in_progress = False
        session.cost_meter.last_latency_ms = int((time.perf_counter() - started) * 1000)
        await _send(websocket, make_event("server.session.state", session.session_id, session.public_dict()))
        await _send_cost(websocket, session)
        return

    await _send_error(websocket, session.session_id, "unsupported_event", event.type)


async def _send(websocket: WebSocket, event: EventEnvelope) -> None:
    await websocket.send_json(event.model_dump())


async def _send_cost(websocket: WebSocket, session: SessionState) -> None:
    await _send(websocket, make_event("cost.update", session.session_id, session.cost_meter.model_dump()))


async def _send_error(websocket: WebSocket, session_id: str, code: str, detail: Any) -> None:
    await _send(websocket, make_event("error", session_id, {"code": code, "detail": detail}))
