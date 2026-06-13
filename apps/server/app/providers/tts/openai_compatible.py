import asyncio
import base64
import json

import requests

from app.config import Settings
from app.contracts.model_io import TTSInput, TTSResult
from app.providers.tts.base import TTSProvider


class OpenAICompatibleTTSProvider(TTSProvider):
    provider_name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.openai_compatible_tts_base_url or settings.openai_compatible_base_url
        self.api_key = settings.openai_compatible_tts_api_key or settings.openai_compatible_api_key
        self.model = settings.openai_compatible_tts_model
        self.voice = settings.openai_compatible_tts_voice
        self.endpoint_path = settings.openai_compatible_tts_endpoint_path
        self.response_format = settings.openai_compatible_tts_response_format

    async def synthesize(self, data: TTSInput) -> TTSResult:
        if not self.api_key:
            raise RuntimeError("openai_compatible TTS API key is not configured.")
        if not self.base_url:
            raise RuntimeError("openai_compatible TTS base URL is not configured.")
        if not self.model:
            raise RuntimeError("openai_compatible TTS model is not configured.")
        if not data.text.strip():
            return TTSResult(raw={"provider": self.provider_name, "model": self.model})
        return await asyncio.to_thread(self._synthesize_sync, data)

    def _synthesize_sync(self, data: TTSInput) -> TTSResult:
        voice = data.voice if data.voice != "default" else self.voice
        payload = {
            "model": self.model,
            "input": data.text,
            "voice": voice,
            "response_format": self.response_format,
        }
        response = requests.post(
            f"{self.base_url.rstrip('/')}/{self.endpoint_path.strip('/')}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=max(1.0, self.settings.cosyvoice3_timeout_seconds),
        )
        response.raise_for_status()
        audio_bytes, mime = _extract_audio_bytes(response, self.response_format)
        sample_rate = _sample_rate_from_mime(mime) or self.settings.audio_output_sample_rate
        return TTSResult(
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            mime=mime,
            sample_rate=sample_rate,
            channels=self.settings.audio_channels,
            encoding=_encoding_from_mime(mime, self.response_format),
            duration_ms=_pcm_duration_ms(audio_bytes, sample_rate, self.settings.audio_channels, mime),
            raw={"provider": self.provider_name, "model": self.model, "voice": voice},
        )


def _extract_audio_bytes(response: requests.Response, response_format: str) -> tuple[bytes, str]:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if "json" not in content_type:
        return response.content, content_type or _mime_from_format(response_format)

    payload = response.json()
    encoded = (
        payload.get("audio_base64")
        or payload.get("audio")
        or payload.get("data")
        or payload.get("b64_json")
    )
    if isinstance(payload.get("data"), list) and payload["data"]:
        first = payload["data"][0]
        if isinstance(first, dict):
            encoded = first.get("audio") or first.get("b64_json") or encoded
    if not encoded:
        raise RuntimeError("openai_compatible TTS response did not contain audio bytes.")
    return base64.b64decode(str(encoded)), _mime_from_format(str(payload.get("format") or response_format))


def _mime_from_format(response_format: str) -> str:
    normalized = response_format.lower()
    if normalized == "mp3":
        return "audio/mpeg"
    if normalized == "wav":
        return "audio/wav"
    if normalized in {"pcm", "pcm_s16le"}:
        return "audio/pcm;rate=24000"
    if normalized == "opus":
        return "audio/ogg"
    return f"audio/{normalized or 'mpeg'}"


def _encoding_from_mime(mime: str, response_format: str) -> str:
    normalized = mime.lower()
    if normalized.startswith(("audio/pcm", "audio/l16", "audio/linear16")):
        return "pcm_s16le"
    if "wav" in normalized:
        return "wav"
    if "mpeg" in normalized or "mp3" in normalized:
        return "mp3"
    return response_format or "unknown"


def _sample_rate_from_mime(mime: str | None) -> int | None:
    normalized = (mime or "").lower()
    if not normalized or "rate=" not in normalized:
        return None
    try:
        return int(normalized.split("rate=", 1)[1].split(";", 1)[0].strip())
    except ValueError:
        return None


def _pcm_duration_ms(audio_bytes: bytes, sample_rate: int, channels: int, mime: str) -> int | None:
    if not mime.lower().startswith(("audio/pcm", "audio/l16", "audio/linear16")):
        return None
    if not audio_bytes or sample_rate <= 0 or channels <= 0:
        return None
    return int((len(audio_bytes) / (sample_rate * channels * 2)) * 1000)
