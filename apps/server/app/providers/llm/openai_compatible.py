import asyncio
import json
from urllib import request

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult
from app.providers.llm.base import LLMProvider


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        provider_name: str = "openai_compatible",
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings
        self.provider_name = provider_name
        self.base_url = base_url if base_url is not None else settings.openai_compatible_base_url
        self.api_key = api_key if api_key is not None else settings.openai_compatible_api_key
        self.model = model if model is not None else settings.openai_compatible_llm_model

    async def complete(self, data: DialogueInput) -> DialogueResult:
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name} API key is not configured.")
        if not self.base_url:
            raise RuntimeError(f"{self.provider_name} base URL is not configured.")
        if not self.model:
            raise RuntimeError(f"{self.provider_name} LLM model is not configured.")

        return await asyncio.to_thread(self._complete_sync, data)

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        messages = [{"role": item.role, "content": item.content} for item in data.messages]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
        }
        result = self._post_json("/chat/completions", payload)
        text = self._extract_text(result)
        if not text:
            text = "云端模型没有返回文本。"
        return DialogueResult(
            text=text,
            emotion="neutral",
            raw={"provider": self.provider_name, "model": self.model},
        )

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=60) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _extract_text(self, result: dict) -> str:
        choices = result.get("choices") or []
        if not choices:
            return ""

        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    chunks.append(str(item.get("text") or item.get("content") or ""))
                else:
                    chunks.append(str(item))
            return "".join(chunks).strip()
        return str(content).strip()
