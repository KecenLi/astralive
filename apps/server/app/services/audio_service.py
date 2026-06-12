from app.contracts.model_io import TTSInput, TTSResult
from app.providers.tts.base import TTSProvider


class AudioService:
    def __init__(self, provider: TTSProvider) -> None:
        self.provider = provider

    async def synthesize(self, text: str, emotion: str) -> TTSResult:
        return await self.provider.synthesize(TTSInput(text=text, emotion=emotion))

