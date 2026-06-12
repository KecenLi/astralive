from app.contracts.model_io import VisionInput, VisionObject, VisionResult
from app.providers.vision.base import VisionProvider


class MockVisionProvider(VisionProvider):
    async def analyze(self, data: VisionInput) -> VisionResult:
        if data.mode == "focus" or any(word in data.prompt for word in ["小字", "读", "看清楚"]):
            summary = "画面里似乎有需要仔细辨认的细节，建议靠近镜头或框选局部后再看。"
            confidence = 0.64
        elif any(word in data.prompt for word in ["手里", "拿着", "东西"]):
            summary = "我看到用户在镜头前展示物品，但 Mock 模式无法真正识别具体物体。"
            confidence = 0.58
        else:
            summary = "画面中有一位用户在电脑前，桌面上有常见办公物品。"
            confidence = 0.76
        return VisionResult(
            summary=summary,
            objects=[
                VisionObject(label="person", zh="人", confidence=0.91),
                VisionObject(label="desk", zh="桌面", confidence=0.66),
            ],
            confidence=confidence,
            raw={"provider": "mock", "mode": data.mode},
        )

