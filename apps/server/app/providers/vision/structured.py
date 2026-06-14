import json
from collections.abc import Mapping
from typing import Any

from app.contracts.model_io import VisionObject, VisionResult


STRUCTURED_VISION_PROMPT = """\
请分析这张图，并只返回一个紧凑 JSON 对象，不要使用 Markdown 或代码块。
JSON 字段固定如下：
{
  "summary": "中文简短总结，只写可见事实",
  "confidence": 0.0,
  "need_focus": false,
  "focus_reason": null,
  "ocr_text": ["可读到的文字"],
  "objects": [
    {
      "label": "english_label",
      "zh": "中文名称",
      "confidence": 0.0,
      "bbox": [y_min, x_min, y_max, x_max]
    }
  ]
}
要求：
- bbox 使用 normalized 2D box，顺序必须是 [y_min, x_min, y_max, x_max]。
- bbox 坐标范围是 0 到 1000，可以用整数或小数；不确定时省略 bbox。
- 如果图像模糊、文字太小、遮挡严重或无法回答用户问题，设置 need_focus=true，并填写 focus_reason。
- confidence 是 0 到 1 的整体可信度。
- objects 只列出和用户问题或画面主体相关的少量对象。

用户问题：__USER_PROMPT__"""


def build_structured_vision_prompt(user_prompt: str) -> str:
    prompt = user_prompt.strip() or "请描述画面。"
    return STRUCTURED_VISION_PROMPT.replace("__USER_PROMPT__", prompt)


def parse_structured_vision_result(
    text: str,
    *,
    fallback_summary: str,
    fallback_confidence: float,
    raw: dict,
) -> VisionResult:
    payload = _extract_json_object(text)
    if not isinstance(payload, Mapping):
        summary = text.strip() or fallback_summary
        return VisionResult(
            summary=summary,
            confidence=fallback_confidence,
            raw={**raw, "structured_parse_success": False},
        )

    summary = _string(payload.get("summary")) or fallback_summary
    confidence = _confidence(payload.get("confidence"), fallback_confidence)
    need_focus = _bool(payload.get("need_focus"), False)
    focus_reason = _string(payload.get("focus_reason")) or None
    ocr_text = _text_list(payload.get("ocr_text"))
    objects = _objects(payload.get("objects"))

    return VisionResult(
        summary=summary,
        objects=objects,
        ocr_text=ocr_text,
        confidence=confidence,
        need_focus=need_focus,
        focus_reason=focus_reason,
        raw={
            **raw,
            "structured_parse_success": True,
            "structured_keys": sorted(str(key) for key in payload.keys()),
        },
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = _strip_code_fence(text.strip())
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _objects(value: object) -> list[VisionObject]:
    if not isinstance(value, list):
        return []
    objects: list[VisionObject] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = _string(item.get("label"))
        if not label:
            continue
        objects.append(
            VisionObject(
                label=label,
                zh=_string(item.get("zh")) or None,
                confidence=_optional_confidence(item.get("confidence")),
                bbox=_bbox(item.get("bbox")),
            )
        )
    return objects


def _bbox(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    coords: list[float] = []
    for coord in value:
        try:
            number = float(coord)
        except (TypeError, ValueError):
            return None
        if number < 0 or number > 1000:
            return None
        coords.append(number)
    y_min, x_min, y_max, x_max = coords
    if y_max <= y_min or x_max <= x_min:
        return None
    return coords


def _text_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        text = _string(item)
        if text:
            texts.append(text)
    return texts


def _string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _confidence(value: object, fallback: float) -> float:
    parsed = _optional_confidence(value)
    if parsed is None:
        return fallback
    return parsed


def _optional_confidence(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def _bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "需要", "是"}:
            return True
        if normalized in {"false", "no", "0", "不需要", "否"}:
            return False
    return fallback
