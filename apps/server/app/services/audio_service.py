import asyncio
import base64
import contextlib
from collections.abc import AsyncIterator

from app.config import Settings
from app.contracts.model_io import ASRResult, AudioChunkPayload, RealtimeTurnResult, TTSInput, TTSResult
from app.providers.asr.base import ASRProvider
from app.providers.realtime.base import RealtimeAudioStream, RealtimeProvider
from app.providers.tts.base import TTSProvider


# Process-global GPU compute lock. ASR and TTS run in separate per-session
# AudioService instances but share one physical GPU, so the lock must be shared
# across the whole process — not per instance. When local Whisper and CosyVoice
# both hold the GPU, running inference concurrently can exhaust VRAM and kill a
# worker; serializing here makes them stagger.
_GPU_AUDIO_LOCK = asyncio.Lock()

# Providers that actually run heavy local GPU inference and therefore contend.
_LOCAL_GPU_ASR = {"local_whisper"}
_LOCAL_GPU_TTS = {"cosyvoice3"}


class AudioService:
    def __init__(
        self,
        tts_provider: TTSProvider,
        asr_provider: ASRProvider,
        settings: Settings,
        realtime_provider: RealtimeProvider | None = None,
    ) -> None:
        self.tts_provider = tts_provider
        self.asr_provider = asr_provider
        self.realtime_provider = realtime_provider
        self.settings = settings

    def _gpu_contended(self) -> bool:
        """True when local ASR and TTS would compete for the same GPU and
        serialization is enabled."""
        return (
            getattr(self.settings, "gpu_serialize_local_audio", True)
            and self.settings.asr_provider in _LOCAL_GPU_ASR
            and self.settings.tts_provider in _LOCAL_GPU_TTS
        )

    @contextlib.asynccontextmanager
    async def _gpu_slot(self) -> AsyncIterator[None]:
        if self._gpu_contended():
            async with _GPU_AUDIO_LOCK:
                yield
        else:
            yield

    async def synthesize(self, text: str, emotion: str) -> TTSResult:
        async with self._gpu_slot():
            return await self.tts_provider.synthesize(TTSInput(text=text, emotion=emotion))

    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        async with self._gpu_slot():
            return await self.asr_provider.transcribe(audio_bytes, metadata)

    async def prewarm(self) -> None:
        for provider in (self.asr_provider, self.tts_provider):
            prewarm = getattr(provider, "prewarm", None)
            if prewarm:
                await prewarm()

    async def respond_realtime_audio(
        self, audio_bytes: bytes, metadata: dict | None = None
    ) -> RealtimeTurnResult:
        if not self.realtime_provider:
            raise RuntimeError("Realtime provider is not configured.")
        return await self.realtime_provider.respond_to_audio(audio_bytes, metadata)

    async def respond_realtime_text(
        self, text: str, metadata: dict | None = None
    ) -> RealtimeTurnResult:
        if not self.realtime_provider:
            raise RuntimeError("Realtime provider is not configured.")
        return await self.realtime_provider.respond_to_text(text, metadata)

    async def open_realtime_audio_stream(self, metadata: dict | None = None) -> RealtimeAudioStream:
        if not self.realtime_provider:
            raise RuntimeError("Realtime provider is not configured.")
        return await self.realtime_provider.open_audio_stream(metadata)

    def decode_audio_chunk(self, payload: AudioChunkPayload) -> bytes:
        if not payload.data_base64:
            return b""
        audio_bytes = base64.b64decode(payload.data_base64, validate=True)
        if len(audio_bytes) > self.settings.audio_chunk_max_bytes:
            raise ValueError(
                f"Audio chunk exceeds AUDIO_CHUNK_MAX_BYTES ({self.settings.audio_chunk_max_bytes})."
            )
        return audio_bytes

    @property
    def has_realtime(self) -> bool:
        return self.realtime_provider is not None

    @property
    def can_stream_realtime(self) -> bool:
        return bool(self.realtime_provider and self.realtime_provider.supports_audio_streaming)
