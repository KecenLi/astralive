from app.config import Settings
from app.providers.asr.google_genai import GoogleGenAIASRProvider
from app.providers.asr.mock import MockASRProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.llm.ollama import OllamaLLMProvider
from app.providers.llm.vertex_ai import VertexAILLMProvider
from app.providers.realtime.google_genai_live import GoogleGenAILiveProvider
from app.providers.realtime.mock import MockRealtimeProvider
from app.providers.tts.google_genai import GoogleGenAITTSProvider
from app.providers.tts.mock import MockTTSProvider
from app.providers.vision.mock import MockVisionProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider
from app.providers.vision.vertex_ai import VertexAIVisionProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def asr(self):
        if self.settings.asr_provider == "vertex_ai":
            return GoogleGenAIASRProvider(self.settings, mode="vertex_ai")
        if self.settings.asr_provider == "gemini":
            return GoogleGenAIASRProvider(self.settings, mode="gemini")
        return MockASRProvider()

    def vision(self):
        if self.settings.vision_provider == "vertex_ai":
            return VertexAIVisionProvider(self.settings)
        if self.settings.vision_provider == "gemini":
            return OpenAICompatibleVisionProvider(
                self.settings,
                provider_name="gemini",
                base_url=self.settings.gemini_base_url,
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_vision_model,
            )
        if self.settings.vision_provider == "openai_compatible":
            return OpenAICompatibleVisionProvider(self.settings)
        return MockVisionProvider()

    def llm(self):
        if self.settings.llm_provider == "vertex_ai":
            return VertexAILLMProvider(self.settings)
        if self.settings.llm_provider == "gemini":
            return OpenAICompatibleLLMProvider(
                self.settings,
                provider_name="gemini",
                base_url=self.settings.gemini_base_url,
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_llm_model,
            )
        if self.settings.llm_provider == "ollama":
            return OllamaLLMProvider(self.settings)
        if self.settings.llm_provider == "openai_compatible":
            return OpenAICompatibleLLMProvider(self.settings)
        return MockLLMProvider()

    def tts(self):
        if self.settings.tts_provider == "vertex_ai":
            return GoogleGenAITTSProvider(self.settings, mode="vertex_ai")
        if self.settings.tts_provider == "gemini":
            return GoogleGenAITTSProvider(self.settings, mode="gemini")
        return MockTTSProvider()

    def realtime(self):
        if self.settings.realtime_provider == "vertex_ai":
            return GoogleGenAILiveProvider(self.settings, mode="vertex_ai")
        if self.settings.realtime_provider == "gemini":
            return GoogleGenAILiveProvider(self.settings, mode="gemini")
        if self.settings.realtime_provider == "mock":
            return MockRealtimeProvider()
        return None
