from app.contracts.model_io import DialogueInput, DialogueResult
from app.providers.llm.base import LLMProvider


class MockLLMProvider(LLMProvider):
    async def complete(self, data: DialogueInput) -> DialogueResult:
        user_text = data.messages[-1].content if data.messages else ""
        visual = data.visual_summary or "我还没有新的画面摘要。"

        if any(word in user_text for word in ["谢谢", "不错", "很好"]):
            emotion = "happy"
        elif any(word in user_text for word in ["看不清", "看清楚", "读一下", "小字"]):
            emotion = "curious"
        elif any(word in user_text for word in ["什么", "看到", "画面", "手里"]):
            emotion = "thinking"
        else:
            emotion = "neutral"

        if any(word in user_text for word in ["看清楚", "读一下", "小字"]):
            text = "我可以进入高清凝视模式。请把目标靠近镜头，或者在画面里保持稳定。"
        elif any(word in user_text for word in ["看到", "画面", "手里", "拿着", "什么"]):
            text = f"基于刚才的画面，我的观察是：{visual}"
        elif user_text:
            text = f"我听到了：{user_text}。如果你需要我看画面，可以直接问我看到了什么。"
        else:
            text = "我在，已经准备好听你说话了。"

        return DialogueResult(text=text, emotion=emotion, raw={"provider": "mock"})

