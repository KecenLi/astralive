import asyncio
import json
from urllib import request

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult
from app.providers.llm.base import LLMProvider


class OllamaLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, data: DialogueInput) -> DialogueResult:
        if not self.settings.ollama_llm_model:
            raise RuntimeError("OLLAMA_LLM_MODEL is not configured.")

        return await asyncio.to_thread(self._complete_sync, data)

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        messages = [{"role": item.role, "content": item.content} for item in data.messages]

        payload = {
            "model": self.settings.ollama_llm_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.5},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=60) as response:  # noqa: S310
            result = json.loads(response.read().decode("utf-8"))

        text = result.get("message", {}).get("content", "").strip()
        if not text:
            text = "本地模型没有返回文本。"
        return DialogueResult(text=text, emotion="neutral", raw={"provider": "ollama"})
