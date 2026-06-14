import json

import pytest

from app.config import Settings
from app.contracts.model_io import VisionInput
from app.providers.vision.mock import MockVisionProvider
from app.providers.vision.structured import (
    build_structured_vision_prompt,
    parse_structured_vision_result,
)
from app.providers.vision.vertex_ai import VertexAIVisionProvider


class StubVertexAIClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    def generate_content(self, model: str, payload: dict) -> dict:
        self.calls.append((model, payload))
        return {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


def test_structured_prompt_uses_gemini_bbox_convention() -> None:
    prompt = build_structured_vision_prompt("杯子在哪里？")

    assert "[y_min, x_min, y_max, x_max]" in prompt
    assert "0 到 1000" in prompt
    assert "杯子在哪里" in prompt


def test_structured_parser_reads_json_and_drops_invalid_bbox() -> None:
    text = """```json
    {
      "summary": "桌上有一个红杯子。",
      "confidence": 0.82,
      "need_focus": true,
      "focus_reason": "杯身文字太小",
      "ocr_text": "MODVII",
      "objects": [
        {"label": "cup", "zh": "杯子", "confidence": 0.91, "bbox": [120, 220, 720, 660]},
        {"label": "bad", "bbox": [500, 500, 400, 700]}
      ]
    }
    ```"""

    result = parse_structured_vision_result(
        text,
        fallback_summary="fallback",
        fallback_confidence=0.4,
        raw={"provider": "test"},
    )

    assert result.summary == "桌上有一个红杯子。"
    assert result.confidence == pytest.approx(0.82)
    assert result.need_focus is True
    assert result.focus_reason == "杯身文字太小"
    assert result.ocr_text == ["MODVII"]
    assert result.objects[0].label == "cup"
    assert result.objects[0].bbox == [120.0, 220.0, 720.0, 660.0]
    assert result.objects[1].label == "bad"
    assert result.objects[1].bbox is None
    assert result.raw["structured_parse_success"] is True


def test_structured_parser_falls_back_to_text_summary() -> None:
    result = parse_structured_vision_result(
        "只是一段自然语言描述。",
        fallback_summary="fallback",
        fallback_confidence=0.66,
        raw={"provider": "test"},
    )

    assert result.summary == "只是一段自然语言描述。"
    assert result.confidence == pytest.approx(0.66)
    assert result.objects == []
    assert result.raw["structured_parse_success"] is False


async def test_vertex_vision_provider_parses_structured_json() -> None:
    structured = json.dumps(
        {
            "summary": "屏幕上有 MODVII 设置页。",
            "confidence": 0.88,
            "need_focus": False,
            "focus_reason": None,
            "ocr_text": ["MODVII"],
            "objects": [
                {
                    "label": "screen",
                    "zh": "屏幕",
                    "confidence": 0.79,
                    "bbox": [30, 20, 960, 980],
                }
            ],
        },
        ensure_ascii=False,
    )
    client = StubVertexAIClient(structured)
    settings = Settings(
        vision_provider="vertex_ai",
        vertex_ai_project="demo-project",
        vertex_ai_location="global",
        vertex_ai_vision_model="gemini-2.5-flash",
    )
    provider = VertexAIVisionProvider(settings, client=client)  # type: ignore[arg-type]

    result = await provider.analyze(
        VisionInput(image_base64="abc123", mime="image/jpeg", prompt="读一下屏幕", mode="focus")
    )

    assert result.summary == "屏幕上有 MODVII 设置页。"
    assert result.objects[0].bbox == [30.0, 20.0, 960.0, 980.0]
    assert result.ocr_text == ["MODVII"]
    assert result.raw["structured_parse_success"] is True
    prompt = client.calls[0][1]["contents"][0]["parts"][0]["text"]
    assert "[y_min, x_min, y_max, x_max]" in prompt


async def test_mock_vision_provider_populates_focus_and_bbox_fields() -> None:
    provider = MockVisionProvider()

    result = await provider.analyze(
        VisionInput(image_base64="abc123", prompt="小字能看清楚吗？", mode="normal")
    )

    assert result.need_focus is True
    assert result.focus_reason
    assert result.objects[0].bbox == [110, 360, 900, 760]
    assert result.raw["structured_parse_success"] is True
