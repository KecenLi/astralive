from app.contracts.model_io import ASRResult
from app.providers.asr.base import ASRProvider


class MockASRProvider(ASRProvider):
    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        return ASRResult(text="这是 Mock ASR 转写结果。", confidence=0.5, is_final=True)

