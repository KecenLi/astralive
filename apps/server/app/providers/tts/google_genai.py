import asyncio
import base64
from typing import Any, Literal

from app.config import Settings
from app.contracts.model_io import TTSInput, TTSResult
from app.providers.google_genai_client import GoogleGenAIClientFactory
from app.providers.raw_usage import raw_usage_payload
from app.providers.tts.base import TTSProvider


ProviderMode = Literal["gemini", "vertex_ai"]


class GoogleGenAITTSProvider(TTSProvider):
    def __init__(self, settings: Settings, mode: ProviderMode, client: Any | None = None) -> None:
        self.settings = settings
        self.mode = mode
        self.provider_name = mode
        self.model = settings.vertex_ai_tts_model if mode == "vertex_ai" else settings.gemini_tts_model
        self.voice = settings.vertex_ai_tts_voice if mode == "vertex_ai" else settings.gemini_tts_voice
        self._client = client

    async def synthesize(self, data: TTSInput) -> TTSResult:
        if not self.model:
            raise RuntimeError(f"{self.provider_name} TTS model is not configured.")
        if not data.text.strip():
            return TTSResult(raw={"provider": self.provider_name, "model": self.model})
        return await asyncio.to_thread(self._synthesize_sync, data)

    def _make_client(self):
        factory = GoogleGenAIClientFactory(self.settings)
        if self.mode == "vertex_ai":
            return factory.vertex_client()
        return factory.gemini_client()

    def _synthesize_sync(self, data: TTSInput) -> TTSResult:
        from google.genai import types

        voice = data.voice if data.voice != "default" else self.voice
        response = self._get_client().models.generate_content(
            model=self.model,
            contents=data.text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    ),
                    language_code=self.settings.audio_transcription_language,
                ),
            ),
        )
        audio_base64, mime, byte_count = _extract_audio(response)
        sample_rate = _sample_rate_from_mime(mime) or self.settings.audio_output_sample_rate
        return TTSResult(
            audio_base64=audio_base64,
            mime=mime or f"audio/pcm;rate={sample_rate}",
            sample_rate=sample_rate,
            channels=self.settings.audio_channels,
            encoding="pcm_s16le" if _is_pcm_mime(mime) else "unknown",
            duration_ms=_pcm_duration_ms(byte_count, sample_rate, self.settings.audio_channels),
            raw={
                "provider": self.provider_name,
                "model": self.model,
                "voice": voice,
                **raw_usage_payload(response),
            },
        )

    def _get_client(self):
        if self._client is None:
            self._client = self._make_client()
        return self._client


def _extract_audio(response: Any) -> tuple[str, str, int]:
    for candidate in _get_field(response, "candidates") or []:
        content = _get_field(candidate, "content")
        for part in _get_field(content, "parts") or []:
            inline_data = _get_field(part, "inline_data") or _get_field(part, "inlineData")
            if not inline_data:
                continue
            data = _get_field(inline_data, "data")
            if data is None:
                continue
            audio_base64, byte_count = _base64_audio(data)
            mime = _get_field(inline_data, "mime_type") or _get_field(inline_data, "mimeType")
            return audio_base64, str(mime or "audio/pcm;rate=24000"), byte_count
    raise RuntimeError("Gemini TTS response did not contain inline audio data.")


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
