import asyncio
import json
from collections.abc import AsyncIterator

from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult, DialogueStreamChunk
from app.providers.llm.base import LLMProvider
from app.providers.llm.streaming import iter_sse_data, make_streaming_client
from app.providers.raw_usage import raw_usage_payload
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

    async def stream_complete(self, data: DialogueInput) -> AsyncIterator[DialogueStreamChunk]:
        if not self.model:
            raise RuntimeError("VERTEX_AI_LLM_MODEL is not configured.")
        payload = self._payload(data)
        project = self.client._project_id()  # noqa: SLF001
        token = self.client._access_token()  # noqa: SLF001
        endpoint = self.settings.vertex_ai_api_endpoint.rstrip("/")
        location = self.settings.vertex_ai_location
        url = (
            f"{endpoint}/v1/projects/{project}/locations/{location}/publishers/google/"
            f"models/{self.model}:streamGenerateContent?alt=sse"
        )
        raw_base = {"provider": self.provider_name, "model": self.model}
        latest_usage: dict | None = None
        async with make_streaming_client(self.settings.vertex_ai_request_timeout_seconds) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Goog-User-Project": project,
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
                        chunks = chunk if isinstance(chunk, list) else [chunk]
                        for item in chunks:
                            if not isinstance(item, dict):
                                continue
                            usage = item.get("usageMetadata") or item.get("usage_metadata")
                            if isinstance(usage, dict):
                                latest_usage = usage
                            delta = self._extract_text(item)
                            if delta:
                                yield DialogueStreamChunk(delta=delta, raw=raw_base)
                    raw = dict(raw_base)
                    if latest_usage:
                        raw["usageMetadata"] = latest_usage
                    yield DialogueStreamChunk(done=True, raw=raw)
                except asyncio.CancelledError:
                    await response.aclose()
                    raise

    def _complete_sync(self, data: DialogueInput) -> DialogueResult:
        payload = self._payload(data)
        result = self.client.generate_content(self.model, payload)
        text = self._extract_text(result)
        if not text:
            text = "Vertex AI Gemini 没有返回文本。"
        return DialogueResult(
            text=text,
            emotion="neutral",
            raw={
                "provider": self.provider_name,
                "model": self.model,
                **raw_usage_payload(result),
            },
        )

    def _payload(self, data: DialogueInput) -> dict:
        contents: list[dict] = []
        system_parts: list[str] = []

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
        return payload

    def _extract_text(self, result: dict) -> str:
        chunks: list[str] = []
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text")
                if text:
                    chunks.append(str(text))
        return "".join(chunks).strip()
