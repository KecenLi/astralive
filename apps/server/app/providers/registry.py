from app.config import Settings
from app.providers.asr.mock import MockASRProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.llm.ollama import OllamaLLMProvider
from app.providers.tts.mock import MockTTSProvider
from app.providers.vision.mock import MockVisionProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def asr(self):
        return MockASRProvider()

    def vision(self):
        if self.settings.vision_provider == "openai_compatible":
            return OpenAICompatibleVisionProvider(self.settings)
        return MockVisionProvider()

    def llm(self):
        if self.settings.llm_provider == "ollama":
            return OllamaLLMProvider(self.settings)
        if self.settings.llm_provider == "openai_compatible":
            return OpenAICompatibleLLMProvider(self.settings)
        return MockLLMProvider()

    def tts(self):
        return MockTTSProvider()
