import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings
from app.providers import provider_container as container_module
from app.providers.provider_container import (
    PROVIDER_CONTAINER_STATE_KEY,
    ProviderContainer,
    get_provider_container,
)
from app.providers.realtime.google_genai_live import GoogleGenAILiveProvider


def _live_message(text: str = "", *, complete: bool = False) -> dict:
    server_content: dict = {"turnComplete": complete}
    if text:
        server_content["outputTranscription"] = {"text": text}
    return {"serverContent": server_content}


class DelayedLiveSession:
    def __init__(self, steps: list[tuple[float, dict]]) -> None:
        self.steps = steps

    async def receive(self):
        for delay, message in self.steps:
            if delay:
                await asyncio.sleep(delay)
            yield message


async def test_google_genai_live_receive_turn_times_out_waiting_for_first_response() -> None:
    settings = Settings(
        realtime_first_response_timeout_seconds=0.001,
        realtime_stream_gap_timeout_seconds=0.1,
        realtime_turn_max_seconds=0.5,
    )
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=object())

    with pytest.raises(TimeoutError, match="first response"):
        await provider._receive_turn(DelayedLiveSession([(0.05, _live_message("late", complete=True))]))


async def test_google_genai_live_receive_turn_times_out_on_stream_gap() -> None:
    settings = Settings(
        realtime_first_response_timeout_seconds=0.1,
        realtime_stream_gap_timeout_seconds=0.001,
        realtime_turn_max_seconds=0.5,
    )
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=object())

    with pytest.raises(TimeoutError, match="stream gap"):
        await provider._receive_turn(
            DelayedLiveSession(
                [
                    (0, _live_message("partial")),
                    (0.05, _live_message("late", complete=True)),
                ]
            )
        )


async def test_google_genai_live_receive_turn_enforces_turn_max() -> None:
    settings = Settings(
        realtime_first_response_timeout_seconds=0.1,
        realtime_stream_gap_timeout_seconds=0.1,
        realtime_turn_max_seconds=0.001,
    )
    provider = GoogleGenAILiveProvider(settings, mode="vertex_ai", client=object())

    with pytest.raises(TimeoutError, match="exceeded"):
        await provider._receive_turn(
            DelayedLiveSession(
                [
                    (0, _live_message("partial")),
                    (0.05, _live_message("late", complete=True)),
                ]
            )
        )


class AsyncCloseClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_google_genai_live_provider_close_releases_client_once() -> None:
    client = AsyncCloseClient()
    provider = GoogleGenAILiveProvider(Settings(), mode="vertex_ai", client=client)

    await provider.close()
    await provider.close()

    assert client.close_calls == 1


class FakeProvider:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    async def prewarm(self) -> None:
        self.events.append(f"prewarm:{self.name}")

    async def close(self) -> None:
        self.events.append(f"close:{self.name}")


class FakeRealtimeStream:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeRealtimeProvider(FakeProvider):
    async def open_audio_stream(self, metadata: dict | None = None) -> FakeRealtimeStream:
        stream = FakeRealtimeStream(self.name)
        self.events.append(f"stream:{self.name}")
        return stream


class FakeProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.events: list[str] = []
        self.asr_provider = FakeProvider("asr", self.events)
        self.vision_provider = FakeProvider("vision", self.events)
        self.llm_provider = FakeProvider("llm", self.events)
        self.tts_provider = FakeProvider("tts", self.events)
        self.realtime_count = 0

    def asr(self) -> FakeProvider:
        return self.asr_provider

    def vision(self) -> FakeProvider:
        return self.vision_provider

    def llm(self) -> FakeProvider:
        return self.llm_provider

    def tts(self) -> FakeProvider:
        return self.tts_provider

    def realtime(self) -> FakeRealtimeProvider:
        self.realtime_count += 1
        return FakeRealtimeProvider(f"realtime:{self.realtime_count}", self.events)


async def test_provider_container_reuses_shared_providers_prewarms_audio_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "ProviderRegistry", FakeProviderRegistry)
    container = ProviderContainer(Settings())

    asr = container.asr()
    tts = container.tts()

    assert container.asr() is asr
    assert container.tts() is tts

    await container.prewarm_audio()
    assert container._registry.realtime_count == 0

    audio = container.audio_service()
    assert audio.asr_provider is asr
    assert audio.tts_provider is tts

    container.vision()
    container.llm()
    await container.close()

    events = container._registry.events
    assert events[:2] == ["prewarm:asr", "prewarm:tts"]
    assert sorted(event for event in events if event.startswith("close:")) == [
        "close:asr",
        "close:llm",
        "close:realtime:1",
        "close:tts",
        "close:vision",
    ]


async def test_provider_container_does_not_share_realtime_provider_or_stream_between_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_module, "ProviderRegistry", FakeProviderRegistry)
    container = ProviderContainer(Settings(realtime_provider="mock"))

    session_one_audio = container.audio_service()
    session_two_audio = container.audio_service()

    assert session_one_audio.realtime_provider is not session_two_audio.realtime_provider

    stream_one = await session_one_audio.open_realtime_audio_stream()
    stream_two = await session_two_audio.open_realtime_audio_stream()

    assert stream_one is not stream_two
    assert stream_one.name == "realtime:1"
    assert stream_two.name == "realtime:2"

    await container.close_realtime_provider(session_one_audio.realtime_provider)
    await container.close()
    events = container._registry.events
    assert events.count("close:realtime:1") == 1
    assert events.count("close:realtime:2") == 1


class FakeLifecycleProviderContainer:
    instances: list["FakeLifecycleProviderContainer"] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prewarm_calls = 0
        self.close_calls = 0
        self.instances.append(self)

    async def prewarm_audio(self) -> None:
        self.prewarm_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def test_create_app_lifespan_installs_prewarms_and_closes_provider_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", audio_prewarm_enabled=True)
    FakeLifecycleProviderContainer.instances.clear()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "ProviderContainer", FakeLifecycleProviderContainer)

    app = main_module.create_app()

    with TestClient(app) as client:
        response = client.get("/health")
        container = get_provider_container(app)

        assert response.status_code == 200
        assert getattr(app.state, PROVIDER_CONTAINER_STATE_KEY) is container
        assert container.prewarm_calls == 1

    assert container.close_calls == 1
