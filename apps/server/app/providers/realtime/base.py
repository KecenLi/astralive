from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.contracts.model_io import RealtimeStreamEvent, RealtimeTurnResult


class RealtimeAudioStream(ABC):
    @abstractmethod
    async def send_audio(self, audio_bytes: bytes, mime: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def finish_audio(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def receive(self) -> AsyncIterator[RealtimeStreamEvent]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class RealtimeProvider(ABC):
    @property
    def supports_audio_streaming(self) -> bool:
        return False

    @abstractmethod
    async def respond_to_text(self, text: str, metadata: dict | None = None) -> RealtimeTurnResult:
        raise NotImplementedError

    @abstractmethod
    async def respond_to_audio(self, audio_bytes: bytes, metadata: dict | None = None) -> RealtimeTurnResult:
        raise NotImplementedError

    async def open_audio_stream(self, metadata: dict | None = None) -> RealtimeAudioStream:
        raise NotImplementedError
