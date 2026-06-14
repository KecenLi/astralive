from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.contracts.model_io import DialogueInput, DialogueResult, DialogueStreamChunk


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, data: DialogueInput) -> DialogueResult:
        raise NotImplementedError

    async def stream_complete(self, data: DialogueInput) -> AsyncIterator[DialogueStreamChunk]:
        result = await self.complete(data)
        yield DialogueStreamChunk(
            delta=result.text,
            text=result.text,
            emotion=result.emotion,
            should_speak=result.should_speak,
            done=True,
            raw=result.raw,
        )
