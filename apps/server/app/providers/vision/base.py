from abc import ABC, abstractmethod

from app.contracts.model_io import VisionInput, VisionResult


class VisionProvider(ABC):
    @abstractmethod
    async def analyze(self, data: VisionInput) -> VisionResult:
        raise NotImplementedError

