from typing import Literal

from pydantic import BaseModel, Field


class VisionInput(BaseModel):
    image_base64: str
    mime: str = "image/jpeg"
    prompt: str
    mode: Literal["glance", "normal", "focus"] = "normal"
    metadata: dict = Field(default_factory=dict)


class VisionObject(BaseModel):
    label: str
    zh: str | None = None
    confidence: float | None = None


class VisionResult(BaseModel):
    summary: str
    objects: list[VisionObject] = Field(default_factory=list)
    ocr_text: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw: dict = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class DialogueInput(BaseModel):
    messages: list[ChatMessage]
    visual_summary: str | None = None
    user_profile: dict = Field(default_factory=dict)
    system_state: dict = Field(default_factory=dict)


class DialogueResult(BaseModel):
    text: str
    emotion: str = "neutral"
    should_speak: bool = True
    raw: dict = Field(default_factory=dict)


class ASRResult(BaseModel):
    text: str
    confidence: float = 0.0
    is_final: bool = True
    raw: dict = Field(default_factory=dict)


class TTSInput(BaseModel):
    text: str
    voice: str = "default"
    emotion: str = "neutral"
    format: str = "pcm"


class TTSResult(BaseModel):
    audio_base64: str = ""
    mime: str = "audio/pcm;rate=24000"
    sample_rate: int = 24000
    channels: int = 1
    encoding: str = "pcm_s16le"
    duration_ms: int | None = None
    raw: dict = Field(default_factory=dict)


class AudioChunkPayload(BaseModel):
    chunk_id: str
    mime: str = "audio/pcm;rate=16000"
    sample_rate: int = 16000
    channels: int = 1
    encoding: Literal["pcm_s16le", "wav", "mp3", "webm_opus", "unknown"] = "pcm_s16le"
    data_base64: str = ""
    is_final: bool = False
    metadata: dict = Field(default_factory=dict)


class RealtimeTurnResult(BaseModel):
    input_text: str = ""
    output_text: str = ""
    audio_chunks: list[TTSResult] = Field(default_factory=list)
    emotion: str = "neutral"
    raw: dict = Field(default_factory=dict)
