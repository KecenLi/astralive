import asyncio
import json
from collections.abc import AsyncIterator
from urllib import request

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult, DialogueStreamChunk
from app.providers.llm.base import LLMProvider
from app.providers.llm.streaming import content_to_text, iter_sse_data, make_streaming_client
from app.providers.raw_usage import raw_usage_payload


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
        self._ensure_configured()
        return await asyncio.to_thread(self._complete_sync, data)

    async def stream_complete(self, data: DialogueInput) -> AsyncIterator[DialogueStreamChunk]:
        self._ensure_configured()
        payload = self._build_payload(data, stream=True)
        payload["stream_options"] = {"include_usage": True}
        raw_base = {"provider": self.provider_name, "model": self.model}
        latest_usage: dict | None = None
        async with make_streaming_client(60.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                try:
                    response.raise_for_status()
                    async for data_text in iter_sse_data(response):
                        if data_text == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_text)
                        except json.JSONDecodeError:
                            continue
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            latest_usage = usage
                        delta = _extract_stream_delta(chunk)
                        if delta:
                            yield DialogueStreamChunk(delta=delta, raw=raw_base)
                    raw = dict(raw_base)
                    if latest_usage:
                        raw["usage"] = latest_usage
                    yield DialogueStreamChunk(done=True, raw=raw)
                except asyncio.CancelledError:
                    await response.aclose()
                    raise

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        payload = self._build_payload(data)
        result = self._post_json("/chat/completions", payload)
        text = self._extract_text(result)
        if not text:
            text = "云端模型没有返回文本。"
        return DialogueResult(
            text=text,
            emotion="neutral",
            raw={
                "provider": self.provider_name,
                "model": self.model,
                **raw_usage_payload(result),
            },
        )

    def _ensure_configured(self) -> None:
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name} API key is not configured.")
        if not self.base_url:
            raise RuntimeError(f"{self.provider_name} base URL is not configured.")
        if not self.model:
            raise RuntimeError(f"{self.provider_name} LLM model is not configured.")

    def _build_payload(self, data: DialogueInput, *, stream: bool = False) -> dict:
        messages = [{"role": item.role, "content": item.content} for item in data.messages]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
        }
        if stream:
            payload["stream"] = True
        return payload

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
        return content_to_text(content).strip()


def _extract_stream_delta(result: dict) -> str:
    choices = result.get("choices") or []
    if not choices:
        return ""
    chunks: list[str] = []
    for choice in choices:
        delta = choice.get("delta") or {}
        content = content_to_text(delta.get("content"))
        if not content:
            content = content_to_text(choice.get("message", {}).get("content"))
        chunks.append(content)
    return "".join(chunks)
