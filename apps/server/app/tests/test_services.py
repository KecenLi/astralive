from app.config import Settings
from app.contracts.media import FramePayload
from app.core.session_state import SessionState
from app.providers.registry import ProviderRegistry
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider
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
