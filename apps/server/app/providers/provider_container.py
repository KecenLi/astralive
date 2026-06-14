import inspect
from typing import Any

from app.config import Settings
from app.providers.registry import ProviderRegistry
from app.services.audio_service import AudioService
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService


PROVIDER_CONTAINER_STATE_KEY = "provider_container"


class ProviderContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._registry = ProviderRegistry(settings)
        self._shared_providers: dict[str, Any] = {}
        self._realtime_providers: dict[int, Any] = {}

    def asr(self) -> Any:
        return self._get_provider("asr", self._registry.asr)

    def vision(self) -> Any:
        return self._get_provider("vision", self._registry.vision)

    def llm(self) -> Any:
        return self._get_provider("llm", self._registry.llm)

    def tts(self) -> Any:
        return self._get_provider("tts", self._registry.tts)

    def realtime(self) -> Any:
        provider = self._registry.realtime()
        if provider is not None:
            self._realtime_providers[id(provider)] = provider
        return provider

    def audio_service(self) -> AudioService:
        return AudioService(self.tts(), self.asr(), self.settings, self.realtime())

    def dialogue_service(self) -> DialogueService:
        return DialogueService(self.llm(), self.settings)

    def vision_service(self) -> VisionService:
        return VisionService(self.vision(), self.settings)

    async def prewarm_audio(self) -> None:
        for provider in (self.asr(), self.tts()):
            prewarm = getattr(provider, "prewarm", None)
            if not prewarm:
                continue
            result = prewarm()
            if inspect.isawaitable(result):
                await result

    async def close_realtime_provider(self, provider: Any) -> None:
        self._realtime_providers.pop(id(provider), None)
        await self._close_provider(provider)

    async def close(self) -> None:
        seen: set[int] = set()
        providers = list(self._realtime_providers.values()) + list(self._shared_providers.values())
        for provider in reversed(providers):
            if provider is None or id(provider) in seen:
                continue
            seen.add(id(provider))
            await self._close_provider(provider)
        self._realtime_providers.clear()
        self._shared_providers.clear()

    def _get_provider(self, name: str, factory: Any) -> Any:
        if name not in self._shared_providers:
            self._shared_providers[name] = factory()
        return self._shared_providers[name]

    async def _close_provider(self, provider: Any) -> None:
        if provider is None:
            return
        close = getattr(provider, "close", None)
        if not close:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


def get_provider_container(app: Any) -> ProviderContainer:
    return getattr(app.state, PROVIDER_CONTAINER_STATE_KEY)
