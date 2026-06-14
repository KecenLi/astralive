import asyncio

from app.config import Settings
from app.contracts.model_io import VisionInput, VisionResult
from app.providers.raw_usage import raw_usage_payload
from app.providers.vertex_ai_client import VertexAIClient
from app.providers.vision.base import VisionProvider
from app.providers.vision.structured import build_structured_vision_prompt, parse_structured_vision_result


class VertexAIVisionProvider(VisionProvider):
    provider_name = "vertex_ai"

    def __init__(self, settings: Settings, client: VertexAIClient | None = None) -> None:
        self.settings = settings
        self.model = settings.vertex_ai_vision_model
        self.client = client or VertexAIClient(settings)

    async def analyze(self, data: VisionInput) -> VisionResult:
        if not self.model:
            raise RuntimeError("VERTEX_AI_VISION_MODEL is not configured.")
        return await asyncio.to_thread(self._analyze_sync, data)

    def _analyze_sync(self, data: VisionInput) -> VisionResult:
        prompt = build_structured_vision_prompt(data.prompt)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": data.mime, "data": data.image_base64}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        result = self.client.generate_content(self.model, payload)
        summary = self._extract_text(result)
        if not summary:
            summary = "Vertex AI Gemini 没有返回画面描述。"
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

    def _extract_text(self, result: dict) -> str:
        chunks: list[str] = []
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text")
                if text:
                    chunks.append(str(text))
        return "".join(chunks).strip()
