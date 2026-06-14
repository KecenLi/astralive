from app.contracts.model_io import VisionInput, VisionObject, VisionResult
from app.providers.vision.base import VisionProvider


class MockVisionProvider(VisionProvider):
    async def analyze(self, data: VisionInput) -> VisionResult:
        if data.mode == "focus" or any(word in data.prompt for word in ["小字", "读", "看清楚"]):
            summary = "画面里似乎有需要仔细辨认的细节，建议靠近镜头或框选局部后再看。"
            confidence = 0.64
            need_focus = True
            focus_reason = "Mock 检测到用户在询问细节或文字，需要高清 focus 帧。"
        elif any(word in data.prompt for word in ["手里", "拿着", "东西"]):
            summary = "我看到用户在镜头前展示物品，但 Mock 模式无法真正识别具体物体。"
            confidence = 0.58
            need_focus = True
            focus_reason = "Mock 模式无法确认手中物体，需要真实视觉 provider 或更清晰画面。"
        else:
            summary = "画面中有一位用户在电脑前，桌面上有常见办公物品。"
            confidence = 0.76
            need_focus = False
            focus_reason = None
        return VisionResult(
            summary=summary,
            objects=[
                VisionObject(label="person", zh="人", confidence=0.91, bbox=[110, 360, 900, 760]),
                VisionObject(label="desk", zh="桌面", confidence=0.66, bbox=[680, 80, 990, 980]),
            ],
            ocr_text=["MODVII"],
            confidence=confidence,
            need_focus=need_focus,
            focus_reason=focus_reason,
            raw={"provider": "mock", "mode": data.mode, "structured_parse_success": True},
        )
