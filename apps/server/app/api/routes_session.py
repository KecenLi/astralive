from fastapi import APIRouter

from app.api.websocket import sessions
from app.config import get_settings
from app.core.session_state import SessionState

router = APIRouter()


@router.post("/api/session")
async def create_session() -> dict:
    settings = get_settings()
    session = SessionState(wake_word=settings.wake_word)
    sessions[session.session_id] = session
    return session.public_dict()

