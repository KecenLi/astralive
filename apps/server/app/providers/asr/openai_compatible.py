import asyncio
import io
import wave

import requests

from app.config import Settings
from app.contracts.model_io import ASRResult
from app.providers.asr.base import ASRProvider


class OpenAICompatibleASRProvider(ASRProvider):
    provider_name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.openai_compatible_asr_base_url or settings.openai_compatible_base_url
        self.api_key = settings.openai_compatible_asr_api_key or settings.openai_compatible_api_key
        self.model = settings.openai_compatible_asr_model
        self.endpoint_path = settings.openai_compatible_asr_endpoint_path

    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        if not self.api_key:
            raise RuntimeError("openai_compatible ASR API key is not configured.")
        if not self.base_url:
            raise RuntimeError("openai_compatible ASR base URL is not configured.")
        if not self.model:
            raise RuntimeError("openai_compatible ASR model is not configured.")
        if not audio_bytes:
            return ASRResult(text="", confidence=0.0, is_final=True)
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes, metadata or {})

    def _transcribe_sync(self, audio_bytes: bytes, metadata: dict) -> ASRResult:
        upload_bytes, filename, content_type = _audio_upload(audio_bytes, metadata, self.settings)
        data = {
            "model": self.model,
            "language": self.settings.audio_transcription_language,
            "response_format": "json",
        }
        response = requests.post(
            f"{self.base_url.rstrip('/')}/{self.endpoint_path.strip('/')}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data=data,
            files={"file": (filename, upload_bytes, content_type)},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        text = str(payload.get("text") or payload.get("transcript") or "").strip()
        return ASRResult(
            text=text,
            confidence=0.72 if text else 0.0,
            is_final=True,
            raw={"provider": self.provider_name, "model": self.model, "mime": content_type},
        )


def _audio_upload(audio_bytes: bytes, metadata: dict, settings: Settings) -> tuple[bytes, str, str]:
    encoding = str(metadata.get("encoding") or "").lower()
    mime = str(metadata.get("mime") or "").lower()
    if encoding == "pcm_s16le" or mime.startswith("audio/pcm"):
        sample_rate = int(metadata.get("sample_rate") or settings.audio_input_sample_rate)
        channels = int(metadata.get("channels") or settings.audio_channels)
        return _pcm16_to_wav(audio_bytes, sample_rate, channels), "audio.wav", "audio/wav"
    if encoding == "mp3" or "mpeg" in mime or mime.endswith("mp3"):
        return audio_bytes, "audio.mp3", "audio/mpeg"
    if encoding == "webm_opus" or "webm" in mime:
        return audio_bytes, "audio.webm", "audio/webm"
    return audio_bytes, "audio.wav", "audio/wav"


def _pcm16_to_wav(audio_bytes: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)
    return buffer.getvalue()
