import asyncio
import json
from collections.abc import AsyncIterator
from urllib import request

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult, DialogueStreamChunk
from app.providers.llm.base import LLMProvider
from app.providers.llm.streaming import iter_jsonl_data, make_streaming_client


class OllamaLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, data: DialogueInput) -> DialogueResult:
        if not self.settings.ollama_llm_model:
            raise RuntimeError("OLLAMA_LLM_MODEL is not configured.")

        return await asyncio.to_thread(self._complete_sync, data)

    async def stream_complete(self, data: DialogueInput) -> AsyncIterator[DialogueStreamChunk]:
        if not self.settings.ollama_llm_model:
            raise RuntimeError("OLLAMA_LLM_MODEL is not configured.")
        payload = self._build_payload(data, stream=True)
        raw_base = {"provider": "ollama", "model": self.settings.ollama_llm_model}
        final_chunk: dict | None = None
        async with make_streaming_client(60.0) as client:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
            ) as response:
                try:
                    response.raise_for_status()
                    async for line in iter_jsonl_data(response):
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("done"):
                            final_chunk = chunk
                            break
                        content = str((chunk.get("message") or {}).get("content") or "")
                        if content:
                            yield DialogueStreamChunk(delta=content, raw=raw_base)
                    raw = dict(raw_base)
                    if final_chunk:
                        raw["final"] = final_chunk
                    yield DialogueStreamChunk(done=True, raw=raw)
                except asyncio.CancelledError:
                    await response.aclose()
                    raise

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        payload = self._build_payload(data, stream=False)
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

    def _build_payload(self, data: DialogueInput, *, stream: bool) -> dict:
        messages = [{"role": item.role, "content": item.content} for item in data.messages]
        return {
            "model": self.settings.ollama_llm_model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": 0.5},
        }
