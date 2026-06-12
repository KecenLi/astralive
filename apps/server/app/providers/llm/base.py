from abc import ABC, abstractmethod

from app.contracts.model_io import DialogueInput, DialogueResult


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, data: DialogueInput) -> DialogueResult:
        raise NotImplementedError

