import asyncio

from app.contracts.model_io import ChatMessage, DialogueInput, DialogueResult
from app.core.session_state import SessionState
from app.providers.llm.base import LLMProvider


VISUAL_KEYWORDS = ("看", "看到", "画面", "摄像头", "手里", "拿着", "桌上", "读", "小字")
FOCUS_KEYWORDS = ("看清楚", "仔细", "读一下", "小字", "不清楚")


class DialogueService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def needs_vision(self, text: str) -> bool:
        return any(keyword in text for keyword in VISUAL_KEYWORDS)

    def needs_focus(self, text: str) -> bool:
        return any(keyword in text for keyword in FOCUS_KEYWORDS)

    async def reply(self, session: SessionState, user_text: str) -> DialogueResult:
        session.status = "thinking"
        session.last_user_text = user_text
        result = await self.provider.complete(
            DialogueInput(
                messages=[ChatMessage(role="user", content=user_text)],
                visual_summary=session.last_visual_summary,
                system_state=session.public_dict(),
            )
        )
        session.cost_meter.llm_calls += 1
        return result

    async def stream_text(self, text: str):
        for chunk in _chunks(text, 12):
            await asyncio.sleep(0.035)
            yield chunk


def _chunks(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]

