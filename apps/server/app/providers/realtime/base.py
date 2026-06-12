from abc import ABC, abstractmethod

from app.contracts.model_io import RealtimeTurnResult


class RealtimeProvider(ABC):
    @abstractmethod
    async def respond_to_text(self, text: str, metadata: dict | None = None) -> RealtimeTurnResult:
        raise NotImplementedError

    @abstractmethod
    async def respond_to_audio(self, audio_bytes: bytes, metadata: dict | None = None) -> RealtimeTurnResult:
        raise NotImplementedError
