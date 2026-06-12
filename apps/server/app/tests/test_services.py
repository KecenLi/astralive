import asyncio
import time

import pytest

from app.api.websocket import AudioRuntimeState, _handle_event, _handle_realtime_audio_chunk, _next_realtime_stream_event
from app.config import Settings
from app.contracts.events import EventEnvelope
from app.contracts.media import FramePayload
from app.contracts.model_io import (
    AudioChunkPayload,
    ChatMessage,
    DialogueInput,
    RealtimeStreamEvent,
    TTSInput,
    TTSResult,
    VisionInput,
)
from app.core.session_state import SessionState
from app.services.avatar_service import AvatarService
from app.providers.asr.google_genai import GoogleGenAIASRProvider
from app.providers.registry import ProviderRegistry
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.llm.vertex_ai import VertexAILLMProvider
from app.providers.realtime.google_genai_live import GoogleGenAILiveProvider
from app.providers.realtime.mock import MockRealtimeProvider
from app.providers.tts.google_genai import GoogleGenAITTSProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider
from app.providers.vision.vertex_ai import VertexAIVisionProvider
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService
from app.services.wake_service import WakeService


async def test_mock_vision_updates_cost() -> None:
    settings = Settings(vision_provider="mock", llm_provider="mock")
    session = SessionState(wake_word=settings.wake_word)
    registry = ProviderRegistry(settings)
    service = VisionService(registry.vision(), settings)
    result, from_cache = await service.analyze_frame(
        session,
        FramePayload(
            frame_id="frame_test",
            width=640,
            height=360,
            capture_reason="visual_question",
            scene_hash="abc",
            data_base64="abc123",
        ),
        "你看到了什么？",
    )
    assert not from_cache
    assert result.summary
    assert session.cost_meter.frames_uploaded == 1
    assert session.cost_meter.vision_calls == 1


async def test_mock_dialogue_uses_visual_summary() -> None:
    settings = Settings(vision_provider="mock", llm_provider="mock")
    session = SessionState(wake_word=settings.wake_word, last_visual_summary="桌上有一个水杯。")
    registry = ProviderRegistry(settings)
    service = DialogueService(registry.llm())
    result = await service.reply(session, "你看到了什么？")
    assert "桌上有一个水杯" in result.text
    assert session.cost_meter.llm_calls == 1


def test_gemini_llm_provider_uses_gemini_settings() -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        gemini_llm_model="gemini-3.5-flash",
    )
    provider = ProviderRegistry(settings).llm()
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.provider_name == "gemini"
    assert provider.api_key == "test-key"
    assert provider.model == "gemini-3.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_vision_provider_uses_gemini_settings() -> None:
    settings = Settings(
        vision_provider="gemini",
        gemini_api_key="test-key",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        gemini_vision_model="gemini-3.5-flash",
    )
    provider = ProviderRegistry(settings).vision()
    assert isinstance(provider, OpenAICompatibleVisionProvider)
    assert provider.provider_name == "gemini"
    assert provider.api_key == "test-key"
    assert provider.model == "gemini-3.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


class StubVertexAIClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def generate_content(self, model: str, payload: dict) -> dict:
        self.calls.append((model, payload))
        return {"candidates": [{"content": {"parts": [{"text": "Vertex OK"}]}}]}


async def test_vertex_ai_dialogue_provider_builds_generate_content_payload() -> None:
    settings = Settings(
        llm_provider="vertex_ai",
        vertex_ai_project="demo-project",
        vertex_ai_location="global",
        vertex_ai_llm_model="gemini-2.5-flash",
    )
    client = StubVertexAIClient()
    provider = VertexAILLMProvider(settings, client=client)  # type: ignore[arg-type]
    result = await provider.complete(
        DialogueInput(
            messages=[ChatMessage(role="user", content="你好")],
            visual_summary="画面里有一台电脑。",
        )
    )
    assert result.text == "Vertex OK"
    assert client.calls[0][0] == "gemini-2.5-flash"
    payload = client.calls[0][1]
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"][0]["text"] == "你好"
    assert "画面里有一台电脑" in payload["systemInstruction"]["parts"][0]["text"]


async def test_vertex_ai_vision_provider_builds_multimodal_payload() -> None:
    settings = Settings(
        vision_provider="vertex_ai",
        vertex_ai_project="demo-project",
        vertex_ai_location="global",
        vertex_ai_vision_model="gemini-2.5-flash",
    )
    client = StubVertexAIClient()
    provider = VertexAIVisionProvider(settings, client=client)  # type: ignore[arg-type]
    result = await provider.analyze(
        VisionInput(
            image_base64="abc123",
            mime="image/jpeg",
            prompt="这是什么？",
            mode="normal",
        )
    )
    assert result.summary == "Vertex OK"
    assert client.calls[0][0] == "gemini-2.5-flash"
    parts = client.calls[0][1]["contents"][0]["parts"]
    assert "这是什么" in parts[0]["text"]
    assert parts[1]["inlineData"] == {"mimeType": "image/jpeg", "data": "abc123"}


def test_registry_can_select_vertex_ai_providers() -> None:
    settings = Settings(
        llm_provider="vertex_ai",
        vision_provider="vertex_ai",
        asr_provider="vertex_ai",
        tts_provider="vertex_ai",
        realtime_provider="vertex_ai",
    )
    registry = ProviderRegistry(settings)
    assert isinstance(registry.llm(), VertexAILLMProvider)
    assert isinstance(registry.vision(), VertexAIVisionProvider)
    assert isinstance(registry.asr(), GoogleGenAIASRProvider)
    assert isinstance(registry.tts(), GoogleGenAITTSProvider)
    assert isinstance(registry.realtime(), GoogleGenAILiveProvider)


class StubGenAIModels:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.calls: list[dict] = []
        self.mime = mime

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": self.mime,
                                    "data": b"\x00\x00" * 240,
                                }
                            }
                        ]
                    }
                }
            ]
        }


class StubGenAIClient:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.models = StubGenAIModels(mime)


async def test_google_genai_tts_extracts_inline_audio() -> None:
    settings = Settings(tts_provider="vertex_ai")
    client = StubGenAIClient()
    provider = GoogleGenAITTSProvider(settings, mode="vertex_ai", client=client)
    result = await provider.synthesize(TTSInput(text="你好"))

    assert client.models.calls[0]["model"] == settings.vertex_ai_tts_model
    assert result.audio_base64
    assert result.mime == "audio/pcm;rate=24000"
    assert result.sample_rate == 24000
    assert result.duration_ms == 10


async def test_google_genai_tts_treats_l16_as_pcm() -> None:
    settings = Settings(tts_provider="vertex_ai")
    provider = GoogleGenAITTSProvider(
        settings,
        mode="vertex_ai",
        client=StubGenAIClient(mime="audio/L16; codec=pcm; rate=24000; channels=1"),
    )
    result = await provider.synthesize(TTSInput(text="你好"))

    assert result.mime == "audio/L16; codec=pcm; rate=24000; channels=1"
    assert result.sample_rate == 24000
    assert result.encoding == "pcm_s16le"


class StubLiveSession:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.audio_bytes = b""
        self.mime = mime
        self.audio_stream_ended = False
        self.closed = False

    async def send_client_content(self, **kwargs) -> None:
        self.client_content = kwargs

    async def send_realtime_input(self, **kwargs) -> None:
        audio = kwargs.get("audio")
        if audio:
            self.audio_bytes += audio.data
        if kwargs.get("audio_stream_end"):
            self.audio_stream_ended = True

    async def receive(self):
        yield {
            "serverContent": {
                "inputTranscription": {"text": "你好"},
                "outputTranscription": {"text": "收到"},
                "modelTurn": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": self.mime,
                                "data": b"\x00\x00" * 120,
                            }
                        }
                    ]
                },
                "turnComplete": True,
            }
        }

    async def close(self) -> None:
        self.closed = True


class StubLiveConnect:
    def __init__(self, session: StubLiveSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class StubLive:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.session = StubLiveSession(mime)
        self.connect_kwargs: dict = {}

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        return StubLiveConnect(self.session)


class StubAio:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.live = StubLive(mime)


class StubLiveClient:
    def __init__(self, mime: str = "audio/pcm;rate=24000") -> None:
        self.aio = StubAio(mime)


async def test_google_genai_live_merges_transcripts_and_audio_chunks() -> None:
    settings = Settings(realtime_provider="vertex_ai")
    client = StubLiveClient()
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=client)

    result = await provider.respond_to_audio(b"\x01\x02", {"mime": "audio/pcm;rate=16000"})

    assert client.aio.live.connect_kwargs["model"] == settings.vertex_ai_realtime_model
    assert client.aio.live.session.audio_bytes == b"\x01\x02"
    assert result.input_text == "你好"
    assert result.output_text == "收到"
    assert len(result.audio_chunks) == 1
    assert result.audio_chunks[0].sample_rate == 24000


async def test_google_genai_live_treats_l16_as_pcm() -> None:
    settings = Settings(realtime_provider="vertex_ai")
    client = StubLiveClient(mime="audio/L16; codec=pcm; rate=24000; channels=1")
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=client)

    result = await provider.respond_to_audio(b"\x01\x02", {"mime": "audio/pcm;rate=16000"})

    assert result.audio_chunks[0].sample_rate == 24000
    assert result.audio_chunks[0].encoding == "pcm_s16le"


async def test_google_genai_live_audio_stream_sends_chunks_and_receives_events() -> None:
    settings = Settings(realtime_provider="vertex_ai")
    client = StubLiveClient()
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=client)

    stream = await provider.open_audio_stream({"system_instruction": "test"})
    await stream.send_audio(b"\x01\x02", "audio/pcm;rate=16000")
    await stream.send_audio(b"\x03\x04", "audio/pcm;rate=16000")
    await stream.finish_audio()
    events = [event async for event in stream.receive()]
    await stream.close()

    assert client.aio.live.connect_kwargs["model"] == settings.vertex_ai_realtime_model
    assert client.aio.live.session.audio_bytes == b"\x01\x02\x03\x04"
    assert client.aio.live.session.audio_stream_ended is True
    assert client.aio.live.session.closed is True
    assert len(events) == 1
    assert events[0].input_text == "你好"
    assert events[0].output_text == "收到"
    assert events[0].turn_complete is True
    assert events[0].audio_chunks[0].sample_rate == 24000


async def test_mock_realtime_provider_supports_audio_streaming() -> None:
    provider = MockRealtimeProvider()
    stream = await provider.open_audio_stream()
    await stream.send_audio(b"\x01\x02", "audio/pcm;rate=16000")
    await stream.finish_audio()
    events = [event async for event in stream.receive()]

    assert provider.supports_audio_streaming is True
    assert events[0].turn_complete is True
    assert events[0].input_text
    assert events[0].output_text


async def test_realtime_stream_wait_does_not_timeout_before_final_audio() -> None:
    async def events():
        await asyncio.sleep(0.02)
        yield RealtimeStreamEvent(input_text="ok")

    runtime = AudioRuntimeState()
    settings = Settings(realtime_turn_timeout_seconds=0.001)

    event = await _next_realtime_stream_event(events().__aiter__(), runtime, settings)

    assert event.input_text == "ok"


async def test_realtime_stream_wait_times_out_after_final_audio() -> None:
    async def events():
        await asyncio.sleep(60)
        yield RealtimeStreamEvent(input_text="late")

    runtime = AudioRuntimeState()
    runtime.input_finished = True
    runtime.input_finished_at = time.perf_counter() - 1
    settings = Settings(realtime_turn_timeout_seconds=0.001)

    with pytest.raises(TimeoutError):
        await _next_realtime_stream_event(events().__aiter__(), runtime, settings)


class OrderSensitiveRealtimeStream:
    def __init__(self) -> None:
        self.audio_sent = False
        self.closed = False
        self.finished = asyncio.Event()

    async def send_audio(self, audio_bytes: bytes, mime: str) -> None:
        if self.closed:
            raise RuntimeError("stream was closed before first audio chunk")
        self.audio_sent = True

    async def finish_audio(self) -> None:
        self.finished.set()

    async def receive(self):
        await asyncio.sleep(0)
        if not self.audio_sent:
            self.closed = True
            yield RealtimeStreamEvent(turn_complete=True)
            return
        yield RealtimeStreamEvent(turn_complete=True)
        await self.finished.wait()
        yield RealtimeStreamEvent(
            input_text="browser mic ok",
            output_text="live ok",
            audio_chunks=[
                TTSResult(
                    audio_base64="AAAA",
                    mime="audio/pcm;rate=24000",
                    sample_rate=24000,
                    channels=1,
                    encoding="pcm_s16le",
                )
            ],
            turn_complete=True,
        )

    async def close(self) -> None:
        self.closed = True
        self.finished.set()


class StubStreamingAudioService:
    def __init__(self, stream: OrderSensitiveRealtimeStream) -> None:
        self.stream = stream
        self.has_realtime = True
        self.can_stream_realtime = True
        self.synthesize_calls: list[tuple[str, str]] = []

    async def open_realtime_audio_stream(self, metadata: dict | None = None):
        return self.stream

    async def synthesize(self, text: str, emotion: str) -> TTSResult:
        self.synthesize_calls.append((text, emotion))
        return TTSResult(
            audio_base64="AAAA",
            mime="audio/pcm;rate=24000",
            sample_rate=24000,
            channels=1,
            encoding="pcm_s16le",
        )


class AsrOnlyRealtimeStream(OrderSensitiveRealtimeStream):
    async def receive(self):
        await self.finished.wait()
        yield RealtimeStreamEvent(input_text="只返回转写", turn_complete=True)


class StubWebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_json(self, event: dict) -> None:
        await asyncio.sleep(0)
        self.events.append(event)


async def test_realtime_audio_receiver_starts_after_final_audio_chunk() -> None:
    stream = OrderSensitiveRealtimeStream()
    websocket = StubWebSocket()
    runtime = AudioRuntimeState()
    session = SessionState(session_id="test_session")
    settings = Settings(realtime_provider="mock")
    send_lock = asyncio.Lock()
    audio = StubStreamingAudioService(stream)
    dialogue = DialogueService(ProviderRegistry(settings).llm())
    avatar = AvatarService()

    first_payload = AudioChunkPayload(
        chunk_id="chunk_1",
        mime="audio/pcm;rate=16000",
        sample_rate=16000,
        channels=1,
        encoding="pcm_s16le",
        data_base64="",
        is_final=False,
    )
    task = await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        first_payload,
        b"\x00\x00" * 160,
        0.0,
        send_lock,
        None,
    )

    assert stream.audio_sent is True
    assert task is None
    assert runtime.receive_task is None
    assert not any(event["type"] == "error" for event in websocket.events)

    final_payload = first_payload.model_copy(update={"chunk_id": "chunk_final", "is_final": True})
    task = await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        final_payload,
        b"",
        0.0,
        send_lock,
        task,
    )
    assert task is runtime.receive_task
    if task:
        await asyncio.wait_for(task, timeout=1)

    event_types = [event["type"] for event in websocket.events]
    assert "asr.transcript.final" in event_types
    assert "assistant.audio.done" in event_types


async def test_realtime_asr_only_result_falls_back_to_dialogue_tts() -> None:
    stream = AsrOnlyRealtimeStream()
    websocket = StubWebSocket()
    runtime = AudioRuntimeState()
    session = SessionState(session_id="test_session")
    settings = Settings(realtime_provider="mock", llm_provider="mock", tts_provider="vertex_ai")
    send_lock = asyncio.Lock()
    audio = StubStreamingAudioService(stream)
    dialogue = DialogueService(ProviderRegistry(settings).llm())
    avatar = AvatarService()
    first_payload = AudioChunkPayload(
        chunk_id="chunk_1",
        mime="audio/pcm;rate=16000",
        sample_rate=16000,
        channels=1,
        encoding="pcm_s16le",
        data_base64="",
        is_final=False,
    )

    await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        first_payload,
        b"\x00\x00" * 160,
        0.0,
        send_lock,
        None,
    )
    task = await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        first_payload.model_copy(update={"chunk_id": "chunk_final", "is_final": True}),
        b"",
        0.0,
        send_lock,
        None,
    )
    if task:
        await asyncio.wait_for(task, timeout=1)

    event_types = [event["type"] for event in websocket.events]
    audio_done_events = [event for event in websocket.events if event["type"] == "assistant.audio.done"]
    assert session.last_user_text == "只返回转写"
    assert audio.synthesize_calls
    assert "asr.transcript.final" in event_types
    assert "assistant.text.final" in event_types
    assert "assistant.audio.chunk" in event_types
    assert audio_done_events[-1]["payload"]["source"] == "tts"


async def test_user_text_closes_active_realtime_audio_stream() -> None:
    stream = OrderSensitiveRealtimeStream()
    websocket = StubWebSocket()
    runtime = AudioRuntimeState()
    session = SessionState(session_id="test_session")
    settings = Settings(realtime_provider="mock", llm_provider="mock", tts_provider="mock")
    send_lock = asyncio.Lock()
    audio = StubStreamingAudioService(stream)
    dialogue = DialogueService(ProviderRegistry(settings).llm())
    avatar = AvatarService()
    first_payload = AudioChunkPayload(
        chunk_id="chunk_1",
        mime="audio/pcm;rate=16000",
        sample_rate=16000,
        channels=1,
        encoding="pcm_s16le",
        data_base64="",
        is_final=False,
    )

    await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        first_payload,
        b"\x00\x00" * 160,
        0.0,
        send_lock,
        None,
    )
    assert runtime.stream is stream
    assert not stream.closed

    task = await _handle_event(
        websocket,  # type: ignore[arg-type]
        EventEnvelope(type="client.user.text", session_id=session.session_id, payload={"text": "文本打断"}),
        session,
        object(),  # type: ignore[arg-type]
        dialogue,
        audio,  # type: ignore[arg-type]
        avatar,
        WakeService(),
        settings,
        runtime,
        0.0,
        send_lock,
        None,
    )
    if task:
        await asyncio.wait_for(task, timeout=1)

    event_types = [event["type"] for event in websocket.events]
    assert stream.closed is True
    assert runtime.stream is None
    assert runtime.turn_bytes == 0
    assert "assistant.text.final" in event_types


async def test_wake_closes_active_realtime_audio_stream() -> None:
    stream = OrderSensitiveRealtimeStream()
    websocket = StubWebSocket()
    runtime = AudioRuntimeState()
    session = SessionState(session_id="test_session")
    settings = Settings(realtime_provider="mock", llm_provider="mock")
    send_lock = asyncio.Lock()
    audio = StubStreamingAudioService(stream)
    dialogue = DialogueService(ProviderRegistry(settings).llm())
    avatar = AvatarService()
    first_payload = AudioChunkPayload(
        chunk_id="chunk_1",
        mime="audio/pcm;rate=16000",
        sample_rate=16000,
        channels=1,
        encoding="pcm_s16le",
        data_base64="",
        is_final=False,
    )

    await _handle_realtime_audio_chunk(
        websocket,  # type: ignore[arg-type]
        session,
        audio,  # type: ignore[arg-type]
        dialogue,
        avatar,
        settings,
        runtime,
        first_payload,
        b"\x00\x00" * 160,
        0.0,
        send_lock,
        None,
    )
    assert runtime.stream is stream
    assert not stream.closed

    task = await _handle_event(
        websocket,  # type: ignore[arg-type]
        EventEnvelope(type="client.wake.detected", session_id=session.session_id, payload={"wake_word": "阿斯塔"}),
        session,
        object(),  # type: ignore[arg-type]
        dialogue,
        audio,  # type: ignore[arg-type]
        avatar,
        WakeService(),
        settings,
        runtime,
        0.0,
        send_lock,
        None,
    )

    event_types = [event["type"] for event in websocket.events]
    assert task is None
    assert stream.closed is True
    assert runtime.stream is None
    assert runtime.turn_bytes == 0
    assert session.status == "listening"
    assert "server.session.state" in event_types
