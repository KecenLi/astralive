from app.contracts.model_io import RealtimeTurnResult, TTSResult
from app.providers.realtime.base import RealtimeProvider


class MockRealtimeProvider(RealtimeProvider):
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
