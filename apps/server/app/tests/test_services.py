from app.config import Settings
from app.contracts.media import FramePayload
from app.contracts.model_io import ChatMessage, DialogueInput, VisionInput
from app.core.session_state import SessionState
from app.providers.registry import ProviderRegistry
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.llm.vertex_ai import VertexAILLMProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider
from app.providers.vision.vertex_ai import VertexAIVisionProvider
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService


async def test_mock_vision_updates_cost() -> None:
    settings = Settings(vision_provider="mock", llm_provider="mock")
    session = SessionState(wake_word=settings.wake_word)
    registry = ProviderRegistry(settings)
    service = VisionService(registry.vision(), settings)
    result, from_cache = await service.analyze_frame(
        session,
        FramePayload(
            frame_id="frame_test",
            width=640,
            height=360,
            capture_reason="visual_question",
            scene_hash="abc",
            data_base64="abc123",
        ),
        "你看到了什么？",
    )
    assert not from_cache
    assert result.summary
    assert session.cost_meter.frames_uploaded == 1
    assert session.cost_meter.vision_calls == 1


async def test_mock_dialogue_uses_visual_summary() -> None:
    settings = Settings(vision_provider="mock", llm_provider="mock")
    session = SessionState(wake_word=settings.wake_word, last_visual_summary="桌上有一个水杯。")
    registry = ProviderRegistry(settings)
    service = DialogueService(registry.llm())
    result = await service.reply(session, "你看到了什么？")
    assert "桌上有一个水杯" in result.text
    assert session.cost_meter.llm_calls == 1


def test_gemini_llm_provider_uses_gemini_settings() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        gemini_llm_model="gemini-3.5-flash",
    )
    provider = ProviderRegistry(settings).llm()
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.provider_name == "gemini"
    assert provider.api_key == "test-key"
    assert provider.model == "gemini-3.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_vision_provider_uses_gemini_settings() -> None:
    settings = Settings(
        vision_provider="gemini",
        gemini_api_key="test-key",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        gemini_vision_model="gemini-3.5-flash",
    )
    provider = ProviderRegistry(settings).vision()
    assert isinstance(provider, OpenAICompatibleVisionProvider)
    assert provider.provider_name == "gemini"
    assert provider.api_key == "test-key"
    assert provider.model == "gemini-3.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


class StubVertexAIClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def generate_content(self, model: str, payload: dict) -> dict:
        self.calls.append((model, payload))
        return {"candidates": [{"content": {"parts": [{"text": "Vertex OK"}]}}]}


async def test_vertex_ai_dialogue_provider_builds_generate_content_payload() -> None:
    settings = Settings(
        llm_provider="vertex_ai",
        vertex_ai_project="demo-project",
        vertex_ai_location="global",
        vertex_ai_llm_model="gemini-2.5-flash",
    )
    client = StubVertexAIClient()
    provider = VertexAILLMProvider(settings, client=client)  # type: ignore[arg-type]
    result = await provider.complete(
        DialogueInput(
            messages=[ChatMessage(role="user", content="你好")],
            visual_summary="画面里有一台电脑。",
        )
    )
    assert result.text == "Vertex OK"
    assert client.calls[0][0] == "gemini-2.5-flash"
    payload = client.calls[0][1]
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"] == "你好"
    assert "画面里有一台电脑" in payload["systemInstruction"]["parts"][0]["text"]


async def test_vertex_ai_vision_provider_builds_multimodal_payload() -> None:
    settings = Settings(
        vision_provider="vertex_ai",
        vertex_ai_project="demo-project",
        vertex_ai_location="global",
        vertex_ai_vision_model="gemini-2.5-flash",
    )
    client = StubVertexAIClient()
    provider = VertexAIVisionProvider(settings, client=client)  # type: ignore[arg-type]
    result = await provider.analyze(
        VisionInput(
            image_base64="abc123",
            mime="image/jpeg",
            prompt="这是什么？",
            mode="normal",
        )
    )
    assert result.summary == "Vertex OK"
    assert client.calls[0][0] == "gemini-2.5-flash"
    parts = client.calls[0][1]["contents"][0]["parts"]
    assert "这是什么" in parts[0]["text"]
    assert parts[1]["inlineData"] == {"mimeType": "image/jpeg", "data": "abc123"}


def test_registry_can_select_vertex_ai_providers() -> None:
    settings = Settings(llm_provider="vertex_ai", vision_provider="vertex_ai")
    registry = ProviderRegistry(settings)
    assert isinstance(registry.llm(), VertexAILLMProvider)
    assert isinstance(registry.vision(), VertexAIVisionProvider)
