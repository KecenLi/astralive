import asyncio

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult
from app.providers.llm.base import LLMProvider
from app.providers.vertex_ai_client import VertexAIClient


class VertexAILLMProvider(LLMProvider):
    provider_name = "vertex_ai"

    def __init__(self, settings: Settings, client: VertexAIClient | None = None) -> None:
        self.settings = settings
        self.model = settings.vertex_ai_llm_model
        self.client = client or VertexAIClient(settings)

    async def complete(self, data: DialogueInput) -> DialogueResult:
        if not self.model:
            raise RuntimeError("VERTEX_AI_LLM_MODEL is not configured.")
        return await asyncio.to_thread(self._complete_sync, data)

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        contents: list[dict] = []
        system_parts: list[str] = []

        if data.visual_summary:
            system_parts.append(f"你是 AstraLive。请结合这个视觉摘要回答：{data.visual_summary}")

        for item in data.messages:
            if item.role == "system":
                system_parts.append(item.content)
                continue
            role = "model" if item.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": item.content}]})

        payload: dict = {
            "contents": contents or [{"role": "user", "parts": [{"text": "你好"}]}],
            "generationConfig": {"temperature": 0.5},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        result = self.client.generate_content(self.model, payload)
        text = self._extract_text(result)
        if not text:
            text = "Vertex AI Gemini 没有返回文本。"
        return DialogueResult(
            text=text,
            emotion="neutral",
            raw={"provider": self.provider_name, "model": self.model},
        )

    def _extract_text(self, result: dict) -> str:
        chunks: list[str] = []
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text")
                if text:
                    chunks.append(str(text))
        return "".join(chunks).strip()
