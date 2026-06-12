import asyncio
import time
from typing import Any, Literal

from app.config import Settings
from app.contracts.model_io import ASRResult
from app.providers.asr.base import ASRProvider
from app.providers.google_genai_client import GoogleGenAIClientFactory


ProviderMode = Literal["gemini", "vertex_ai"]


class GoogleGenAIASRProvider(ASRProvider):
    def __init__(self, settings: Settings, mode: ProviderMode, client: Any | None = None) -> None:
        self.settings = settings
        self.mode = mode
        self.provider_name = mode
        self.model = settings.vertex_ai_asr_model if mode == "vertex_ai" else settings.gemini_asr_model
        self.batch_model = settings.vertex_ai_llm_model if mode == "vertex_ai" else settings.gemini_llm_model
        self._client = client

    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        if not self.model:
            raise RuntimeError(f"{self.provider_name} ASR model is not configured.")
        if not audio_bytes:
            return ASRResult(text="", confidence=0.0, is_final=True)
        metadata = metadata or {}
        mime = _normalize_audio_mime(
            str(metadata.get("mime") or f"audio/pcm;rate={self.settings.audio_input_sample_rate}")
        )
        if _is_live_pcm_mime(mime, self.settings.audio_input_sample_rate):
            return await self._transcribe_live(audio_bytes, mime)
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes, {**metadata, "mime": mime})

    def _make_client(self):
        factory = GoogleGenAIClientFactory(self.settings)
        if self.mode == "vertex_ai":
            return factory.vertex_client()
        return factory.gemini_client()

    def _transcribe_sync(self, audio_bytes: bytes, metadata: dict) -> ASRResult:
        from google.genai import types

        mime = _normalize_audio_mime(
            str(metadata.get("mime") or f"audio/pcm;rate={self.settings.audio_input_sample_rate}")
        )
        prompt = (
            "请将这段音频转写为原语言文本。只返回转写内容，不要添加解释。"
            f"如果听不清，请返回空字符串。语言优先按 {self.settings.audio_transcription_language} 处理。"
        )
        response = self._get_client().models.generate_content(
            model=self.batch_model,
            contents=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=audio_bytes, mime_type=mime),
            ],
        )
        text = _extract_text(response).strip()
        return ASRResult(
            text=text,
            confidence=0.65 if text else 0.0,
            is_final=True,
            raw={"provider": self.provider_name, "model": self.batch_model, "mime": mime},
        )

    def _get_client(self):
        if self._client is None:
            self._client = self._make_client()
        return self._client

    async def _transcribe_live(self, audio_bytes: bytes, mime: str) -> ASRResult:
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[self.settings.audio_transcription_language]
            ),
        )
        started = time.monotonic()
        transcript = ""
        timed_out = False
        async with self._get_client().aio.live.connect(model=self.model, config=config) as session:
            await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime))
            await session.send_realtime_input(audio_stream_end=True)
            iterator = session.receive().__aiter__()
            while True:
                remaining = self.settings.realtime_turn_timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Gemini Live ASR timed out while waiting for transcription.")
                try:
                    message = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except TimeoutError:
                    timed_out = True
                    break
                except StopAsyncIteration:
                    break
                server_content = _get_field(message, "server_content") or _get_field(
                    message, "serverContent"
                )
                input_transcription = _get_field(server_content, "input_transcription") or _get_field(
                    server_content, "inputTranscription"
                )
                text = _get_field(input_transcription, "text")
                if text:
                    transcript += str(text)
                if _get_field(input_transcription, "finished"):
                    break
                if _get_field(server_content, "turn_complete") or _get_field(
                    server_content, "turnComplete"
                ):
                    break
        transcript = transcript.strip()
        if timed_out and not transcript:
            raise TimeoutError("Gemini Live ASR timed out before returning a transcription.")
        return ASRResult(
            text=transcript,
            confidence=0.75 if transcript else 0.0,
            is_final=True,
            raw={"provider": self.provider_name, "model": self.model, "mime": mime, "mode": "live"},
        )


def _extract_text(response: Any) -> str:
    direct_text = _get_field(response, "text")
    if direct_text:
        return str(direct_text)
    chunks: list[str] = []
    for candidate in _get_field(response, "candidates") or []:
        content = _get_field(candidate, "content")
        for part in _get_field(content, "parts") or []:
            text = _get_field(part, "text")
            if text:
                chunks.append(str(text))
    return "".join(chunks)


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalize_audio_mime(mime: str) -> str:
    normalized = mime.lower()
    if normalized.startswith(("audio/l16", "audio/linear16")):
        rate = "24000"
        if "rate=" in normalized:
            rate = normalized.split("rate=", 1)[1].split(";", 1)[0].strip()
        return f"audio/pcm;rate={rate}"
    return mime


def _is_live_pcm_mime(mime: str, sample_rate: int) -> bool:
    normalized = mime.lower().replace(" ", "")
    return normalized.startswith("audio/pcm") and f"rate={sample_rate}" in normalized
