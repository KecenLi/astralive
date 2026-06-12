import asyncio
import json
from urllib import request

from app.config import Settings
from app.contracts.model_io import VisionInput, VisionResult
from app.providers.vision.base import VisionProvider


class OpenAICompatibleVisionProvider(VisionProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, data: VisionInput) -> VisionResult:
        if not self.settings.openai_compatible_api_key:
            raise RuntimeError("OPENAI_COMPATIBLE_API_KEY is not configured.")
        if not self.settings.openai_compatible_base_url:
            raise RuntimeError("OPENAI_COMPATIBLE_BASE_URL is not configured.")
        if not self.settings.openai_compatible_vision_model:
            raise RuntimeError("OPENAI_COMPATIBLE_VISION_MODEL is not configured.")

        return await asyncio.to_thread(self._analyze_sync, data)

    def _analyze_sync(self, data: VisionInput) -> VisionResult:
        detail = "high" if data.mode == "focus" else "low"
        prompt = (
            "请用中文简短总结画面。只描述和用户问题相关的可见事实；"
            "如果画面太模糊或信息不足，请明确说需要更清晰画面。\n\n"
            f"用户问题：{data.prompt}"
        )
        payload = {
            "model": self.settings.openai_compatible_vision_model,
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

        return VisionResult(
            summary=summary,
            confidence=0.72 if data.mode == "focus" else 0.66,
            raw={
                "provider": "openai_compatible",
                "model": self.settings.openai_compatible_vision_model,
                "mode": data.mode,
            },
        )

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.settings.openai_compatible_base_url.rstrip('/')}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.openai_compatible_api_key}",
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
