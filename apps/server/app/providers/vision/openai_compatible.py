import asyncio
import json
from urllib import request

from app.config import Settings
from app.contracts.model_io import VisionInput, VisionResult
from app.providers.raw_usage import raw_usage_payload
from app.providers.vision.base import VisionProvider
from app.providers.vision.structured import build_structured_vision_prompt, parse_structured_vision_result


class OpenAICompatibleVisionProvider(VisionProvider):
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
        self.model = model if model is not None else settings.openai_compatible_vision_model

    async def analyze(self, data: VisionInput) -> VisionResult:
        if not self.api_key:
            raise RuntimeError(f"{self.provider_name} API key is not configured.")
        if not self.base_url:
            raise RuntimeError(f"{self.provider_name} base URL is not configured.")
        if not self.model:
            raise RuntimeError(f"{self.provider_name} vision model is not configured.")

        return await asyncio.to_thread(self._analyze_sync, data)

    def _analyze_sync(self, data: VisionInput) -> VisionResult:
        detail = "high" if data.mode == "focus" else "low"
        prompt = build_structured_vision_prompt(data.prompt)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{data.mime};base64,{data.image_base64}",
                                "detail": detail,
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.2,
        }
        result = self._post_json("/chat/completions", payload)
        summary = self._extract_text(result)
        if not summary:
            summary = "云端视觉模型没有返回画面描述。"

        return parse_structured_vision_result(
            summary,
            fallback_summary=summary,
            fallback_confidence=0.72 if data.mode == "focus" else 0.66,
            raw={
                "provider": self.provider_name,
                "model": self.model,
                "mode": data.mode,
                **raw_usage_payload(result),
            },
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
