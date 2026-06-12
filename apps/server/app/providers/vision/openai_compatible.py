from app.config import Settings
from app.contracts.model_io import VisionInput, VisionResult
from app.providers.vision.base import VisionProvider


class OpenAICompatibleVisionProvider(VisionProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, data: VisionInput) -> VisionResult:
        if not self.settings.openai_compatible_api_key:
            raise RuntimeError("OPENAI_COMPATIBLE_API_KEY is not configured.")
        raise NotImplementedError("OpenAI-compatible vision provider is reserved for phase 2.")

