from abc import ABC, abstractmethod

from app.contracts.model_io import TTSInput, TTSResult


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, data: TTSInput) -> TTSResult:
        raise NotImplementedError

