import asyncio
import base64
import time
from typing import Any, Literal

from app.config import Settings
from app.contracts.model_io import RealtimeTurnResult, TTSResult
from app.providers.google_genai_client import GoogleGenAIClientFactory
from app.providers.realtime.base import RealtimeProvider


ProviderMode = Literal["gemini", "vertex_ai"]


class GoogleGenAILiveProvider(RealtimeProvider):
    def __init__(self, settings: Settings, mode: ProviderMode, client: Any | None = None) -> None:
        self.settings = settings
        self.mode = mode
        self.provider_name = mode
        self.model = (
            settings.vertex_ai_realtime_model if mode == "vertex_ai" else settings.gemini_realtime_model
        )
        self.voice = settings.vertex_ai_tts_voice if mode == "vertex_ai" else settings.gemini_tts_voice
        self._client = client

    async def respond_to_text(self, text: str, metadata: dict | None = None) -> RealtimeTurnResult:
        if not self.model:
            raise RuntimeError(f"{self.provider_name} realtime model is not configured.")
        metadata = metadata or {}
        from google.genai import types

        async with self._get_client().aio.live.connect(model=self.model, config=self._config(metadata)) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
                turn_complete=True,
            )
            result = await self._receive_turn(session)
            result.input_text = result.input_text or text
            return result

    async def respond_to_audio(self, audio_bytes: bytes, metadata: dict | None = None) -> RealtimeTurnResult:
        if not self.model:
            raise RuntimeError(f"{self.provider_name} realtime model is not configured.")
        if not audio_bytes:
            return RealtimeTurnResult(raw={"provider": self.provider_name, "model": self.model})
        metadata = metadata or {}
        mime = str(metadata.get("mime") or f"audio/pcm;rate={self.settings.audio_input_sample_rate}")
        from google.genai import types

        async with self._get_client().aio.live.connect(model=self.model, config=self._config(metadata)) as session:
            await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime))
            await session.send_realtime_input(audio_stream_end=True)
            return await self._receive_turn(session)

    def _make_client(self):
        factory = GoogleGenAIClientFactory(self.settings)
        if self.mode == "vertex_ai":
            return factory.vertex_client()
        return factory.gemini_client()

    def _get_client(self):
        if self._client is None:
            self._client = self._make_client()
        return self._client

    def _config(self, metadata: dict):
        from google.genai import types

        system_instruction = metadata.get("system_instruction")
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                ),
                language_code=self.settings.audio_transcription_language,
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[self.settings.audio_transcription_language]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[self.settings.audio_transcription_language]
            ),
            system_instruction=system_instruction,
        )

    async def _receive_turn(self, session: Any) -> RealtimeTurnResult:
        started = time.monotonic()
        iterator = session.receive().__aiter__()
        result = RealtimeTurnResult(raw={"provider": self.provider_name, "model": self.model})
        while True:
            remaining = self.settings.realtime_turn_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Gemini Live turn timed out while waiting for a response.")
            try:
                message = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break
            _merge_live_message(result, message, self.settings)
            server_content = _get_field(message, "server_content") or _get_field(message, "serverContent")
            if _get_field(server_content, "turn_complete") or _get_field(server_content, "turnComplete"):
                break
        result.input_text = result.input_text.strip()
        result.output_text = result.output_text.strip()
        return result


def _merge_live_message(result: RealtimeTurnResult, message: Any, settings: Settings) -> None:
    server_content = _get_field(message, "server_content") or _get_field(message, "serverContent")
    if server_content:
        input_transcription = _get_field(server_content, "input_transcription") or _get_field(
            server_content, "inputTranscription"
        )
        output_transcription = _get_field(server_content, "output_transcription") or _get_field(
            server_content, "outputTranscription"
        )
        input_text = _get_field(input_transcription, "text")
        output_text = _get_field(output_transcription, "text")
        if input_text:
            result.input_text += str(input_text)
        if output_text:
            result.output_text += str(output_text)

        model_turn = _get_field(server_content, "model_turn") or _get_field(server_content, "modelTurn")
        for part in _get_field(model_turn, "parts") or []:
            text = _get_field(part, "text")
            if text:
                result.output_text += str(text)
            inline_data = _get_field(part, "inline_data") or _get_field(part, "inlineData")
            if inline_data:
                chunk = _audio_chunk_from_inline_data(inline_data, settings)
                if chunk.audio_base64:
                    result.audio_chunks.append(chunk)

    usage = _get_field(message, "usage_metadata") or _get_field(message, "usageMetadata")
    if usage:
        result.raw["usage_seen"] = True


def _audio_chunk_from_inline_data(inline_data: Any, settings: Settings) -> TTSResult:
    data = _get_field(inline_data, "data")
    mime = _get_field(inline_data, "mime_type") or _get_field(inline_data, "mimeType")
    if data is None:
        return TTSResult(raw={"provider": "google_genai_live"})
    audio_base64, byte_count = _base64_audio(data)
    mime = str(mime or f"audio/pcm;rate={settings.audio_output_sample_rate}")
    sample_rate = _sample_rate_from_mime(mime) or settings.audio_output_sample_rate
    return TTSResult(
        audio_base64=audio_base64,
        mime=mime,
        sample_rate=sample_rate,
        channels=settings.audio_channels,
        encoding="pcm_s16le" if _is_pcm_mime(mime) else "unknown",
        duration_ms=_pcm_duration_ms(byte_count, sample_rate, settings.audio_channels),
        raw={"provider": "google_genai_live"},
    )


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _base64_audio(value: bytes | str) -> tuple[str, int]:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii"), len(value)
    try:
        decoded = base64.b64decode(value, validate=True)
        return value, len(decoded)
    except Exception:  # noqa: BLE001
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return encoded, len(value)


def _sample_rate_from_mime(mime: str | None) -> int | None:
    normalized = (mime or "").lower()
    if not normalized or "rate=" not in normalized:
        return None
    try:
        return int(normalized.split("rate=", 1)[1].split(";", 1)[0].strip())
    except ValueError:
        return None


def _is_pcm_mime(mime: str | None) -> bool:
    normalized = (mime or "").lower()
    return normalized.startswith(("audio/pcm", "audio/l16", "audio/linear16"))


def _pcm_duration_ms(byte_count: int, sample_rate: int, channels: int) -> int | None:
    if byte_count <= 0 or sample_rate <= 0 or channels <= 0:
        return None
    return int((byte_count / (sample_rate * channels * 2)) * 1000)
