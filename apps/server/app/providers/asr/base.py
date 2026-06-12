from abc import ABC, abstractmethod

from app.contracts.model_io import ASRResult


class ASRProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        raise NotImplementedError

