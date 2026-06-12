from app.contracts.model_io import TTSInput, TTSResult
from app.providers.tts.base import TTSProvider


class MockTTSProvider(TTSProvider):
    async def synthesize(self, data: TTSInput) -> TTSResult:
        return TTSResult(audio_base64="", mime="audio/mpeg", duration_ms=None, raw={"provider": "mock"})

