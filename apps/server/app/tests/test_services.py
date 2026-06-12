from app.config import Settings
from app.contracts.media import FramePayload
from app.contracts.model_io import ChatMessage, DialogueInput, TTSInput, VisionInput
from app.core.session_state import SessionState
from app.providers.asr.google_genai import GoogleGenAIASRProvider
from app.providers.registry import ProviderRegistry
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.providers.llm.vertex_ai import VertexAILLMProvider
from app.providers.realtime.google_genai_live import GoogleGenAILiveProvider
from app.providers.tts.google_genai import GoogleGenAITTSProvider
from app.providers.vision.openai_compatible import OpenAICompatibleVisionProvider
from app.providers.vision.vertex_ai import VertexAIVisionProvider
from app.services.dialogue_service import DialogueService
from app.services.vision_service import VisionService


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

    async def send_client_content(self, **kwargs) -> None:
        self.client_content = kwargs

    async def send_realtime_input(self, **kwargs) -> None:
        audio = kwargs.get("audio")
        if audio:
            self.audio_bytes += audio.data

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
