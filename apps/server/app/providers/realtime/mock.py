import asyncio
from collections.abc import AsyncIterator

from app.contracts.model_io import RealtimeStreamEvent, RealtimeTurnResult, TTSResult
from app.providers.realtime.base import RealtimeAudioStream, RealtimeProvider


class MockRealtimeAudioStream(RealtimeAudioStream):
    def __init__(self) -> None:
        self.audio = bytearray()
        self.finished = asyncio.Event()
        self.closed = False

    async def send_audio(self, audio_bytes: bytes, mime: str) -> None:
        self.audio.extend(audio_bytes)

    async def finish_audio(self) -> None:
        self.finished.set()

    async def receive(self) -> AsyncIterator[RealtimeStreamEvent]:
        await self.finished.wait()
        if self.closed:
            return
        yield RealtimeStreamEvent(
            input_text="这是 Mock Live 流式语音输入。",
            output_text="这是 Mock Live 流式音频回复。",
            audio_chunks=[TTSResult(raw={"provider": "mock_realtime_stream", "bytes": len(self.audio)})],
            turn_complete=True,
            raw={"provider": "mock_realtime_stream"},
        )

    async def close(self) -> None:
        self.closed = True
        self.finished.set()


class MockRealtimeProvider(RealtimeProvider):
    @property
    def supports_audio_streaming(self) -> bool:
        return True

    async def respond_to_text(self, text: str, metadata: dict | None = None) -> RealtimeTurnResult:
        return RealtimeTurnResult(
            input_text=text,
            output_text=f"Mock Live 回复：{text}",
            audio_chunks=[TTSResult(raw={"provider": "mock_realtime"})],
            raw={"provider": "mock_realtime"},
        )

    async def respond_to_audio(self, audio_bytes: bytes, metadata: dict | None = None) -> RealtimeTurnResult:
        return RealtimeTurnResult(
            input_text="这是 Mock Live 语音输入。",
            output_text="这是 Mock Live 音频回复。",
            audio_chunks=[TTSResult(raw={"provider": "mock_realtime", "bytes": len(audio_bytes)})],
            raw={"provider": "mock_realtime"},
        )

    async def open_audio_stream(self, metadata: dict | None = None) -> RealtimeAudioStream:
        return MockRealtimeAudioStream()
