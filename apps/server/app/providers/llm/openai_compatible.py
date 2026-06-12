from app.config import Settings
from app.contracts.model_io import DialogueInput, DialogueResult
from app.providers.llm.base import LLMProvider


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, data: DialogueInput) -> DialogueResult:
        if not self.settings.openai_compatible_api_key:
            raise RuntimeError("OPENAI_COMPATIBLE_API_KEY is not configured.")
        raise NotImplementedError("OpenAI-compatible LLM provider is reserved for phase 2.")

