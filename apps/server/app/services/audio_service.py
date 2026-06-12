import base64

from app.config import Settings
from app.contracts.model_io import ASRResult, AudioChunkPayload, RealtimeTurnResult, TTSInput, TTSResult
from app.providers.asr.base import ASRProvider
from app.providers.realtime.base import RealtimeAudioStream, RealtimeProvider
from app.providers.tts.base import TTSProvider


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

    async def synthesize(self, text: str, emotion: str) -> TTSResult:
        return await self.tts_provider.synthesize(TTSInput(text=text, emotion=emotion))

    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        return await self.asr_provider.transcribe(audio_bytes, metadata)

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
