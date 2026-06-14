import asyncio
import contextlib
import io
import json
import os
import sys
import uuid
import wave
from pathlib import Path

from app.config import Settings
from app.contracts.model_io import ASRResult
from app.providers.asr.base import ASRProvider


class LocalWhisperASRProvider(ASRProvider):
    provider_name = "local_whisper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._worker: _LocalWhisperWorker | None = None

    async def transcribe(self, audio_bytes: bytes, metadata: dict | None = None) -> ASRResult:
        if not audio_bytes:
            return ASRResult(text="", confidence=0.0, is_final=True)
        worker = self._worker
        if worker is None:
            worker = _LocalWhisperWorker(self.settings)
            self._worker = worker

        metadata = metadata or {}
        audio_path = self._write_audio(audio_bytes, metadata)
        try:
            result = await worker.transcribe(audio_path, self.settings.audio_transcription_language)
        finally:
            audio_path.unlink(missing_ok=True)
        text = str(result.get("text") or "").strip()
        return ASRResult(
            text=text,
            confidence=0.72 if text else 0.0,
            is_final=True,
            raw={
                "provider": self.provider_name,
                "model": self.settings.local_asr_model,
                "language": result.get("language"),
                "segments": result.get("segments"),
            },
        )

    async def close(self) -> None:
        if self._worker:
            await self._worker.close()
            self._worker = None

    async def prewarm(self) -> None:
        worker = self._worker
        if worker is None:
            worker = _LocalWhisperWorker(self.settings)
            self._worker = worker
        await worker.ensure_started()

    def _write_audio(self, audio_bytes: bytes, metadata: dict) -> Path:
        output_dir = self.settings.data_dir / "cache" / "asr"
        output_dir.mkdir(parents=True, exist_ok=True)
        encoding = str(metadata.get("encoding") or "").lower()
        mime = str(metadata.get("mime") or "").lower()
        suffix = ".wav"
        if encoding == "mp3" or "mpeg" in mime or mime.endswith("mp3"):
            suffix = ".mp3"
            output = output_dir / f"local-whisper-{uuid.uuid4().hex}{suffix}"
            output.write_bytes(audio_bytes)
            return output
        if encoding == "webm_opus" or "webm" in mime:
            suffix = ".webm"
            output = output_dir / f"local-whisper-{uuid.uuid4().hex}{suffix}"
            output.write_bytes(audio_bytes)
            return output
        output = output_dir / f"local-whisper-{uuid.uuid4().hex}.wav"
        if encoding == "wav" or mime.startswith("audio/wav"):
            output.write_bytes(audio_bytes)
            return output
        sample_rate = int(metadata.get("sample_rate") or self.settings.audio_input_sample_rate)
        channels = int(metadata.get("channels") or self.settings.audio_channels)
        output.write_bytes(_pcm16_to_wav(audio_bytes, sample_rate, channels))
        return output


class _WorkerCrash(Exception):
    """The worker process died or its pipe closed; retry on a clean process."""


class _LocalWhisperWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.stderr_file = None

    async def transcribe(self, audio_path: Path, language: str) -> dict:
        async with self.lock:
            last_error: Exception | None = None
            for _attempt in range(2):
                try:
                    return await self._transcribe_once(audio_path, language)
                except _WorkerCrash as exc:
                    last_error = exc
                    self._terminate()
            raise RuntimeError(f"Local Whisper worker crashed and retry failed: {last_error}") from last_error

    async def _transcribe_once(self, audio_path: Path, language: str) -> dict:
        process = await self._ensure_process()
        request_id = uuid.uuid4().hex
        payload = {
            "id": request_id,
            "audio_path": str(audio_path),
            "language": language,
        }
        if not process.stdin or not process.stdout:
            raise _WorkerCrash("Local Whisper worker pipes are not available.")
        try:
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()
        except (ConnectionResetError, BrokenPipeError, RuntimeError) as exc:
            raise _WorkerCrash(f"Local Whisper worker stdin closed: {exc}") from exc
        started = asyncio.get_running_loop().time()
        while True:
            remaining = self.settings.local_asr_timeout_seconds - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                self._terminate()
                raise RuntimeError("Local Whisper ASR timed out.")
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except TimeoutError as exc:
                self._terminate()
                raise RuntimeError("Local Whisper ASR timed out.") from exc
            if not line:
                code = process.returncode
                raise _WorkerCrash(f"Local Whisper worker exited before returning text. exit_code={code}")
            response = json.loads(line.decode("utf-8"))
            if str(response.get("id") or "") != request_id:
                continue
            if not response.get("ok"):
                raise RuntimeError(f"Local Whisper worker failed: {response.get('error')}")
            return response

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self.process and self.process.returncode is None:
            return self.process
        script = _resolve_script_path(self.settings.local_asr_worker_script, "local_whisper_worker.py")
        python = self.settings.local_asr_python or self.settings.cosyvoice3_python or sys.executable
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.settings.logs_dir / "local-whisper-worker.err.log"
        self.stderr_file = log_path.open("ab")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self.process = await asyncio.create_subprocess_exec(
            *_worker_command(self.settings, script, python),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self.stderr_file,
            env=env,
        )
        return self.process

    async def ensure_started(self) -> None:
        async with self.lock:
            await self._ensure_process()

    def _terminate(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.kill()
        self.process = None
        if self.stderr_file:
            self.stderr_file.close()
            self.stderr_file = None

    async def close(self) -> None:
        process = self.process
        self.process = None
        if process and process.returncode is None:
            if process.stdin:
                process.stdin.close()
                with contextlib.suppress(Exception):
                    await process.stdin.wait_closed()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.5)
            except TimeoutError:
                process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=1.5)
        if self.stderr_file:
            self.stderr_file.close()
            self.stderr_file = None


def _resolve_script_path(configured: str, fallback_name: str) -> Path:
    configured_path = Path(configured)
    candidates = [configured_path]
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates.extend(
            [
                executable.parent / "scripts" / fallback_name,
                executable.parent.parent / "scripts" / fallback_name,
            ]
        )
    candidates.extend(
        [
            Path.cwd() / "scripts" / fallback_name,
            Path(__file__).resolve().parents[5] / "scripts" / fallback_name,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(f"Local Whisper worker script not found: {configured_path}")


def _worker_command(settings: Settings, script: Path, python: str) -> list[str]:
    command = [
        python,
        str(script),
        "--model",
        settings.local_asr_model,
        "--device",
        settings.local_asr_device,
        "--language",
        settings.audio_transcription_language,
    ]
    if settings.local_asr_model_path.strip():
        command.extend(["--model-path", settings.local_asr_model_path.strip()])
    if settings.local_asr_download_root.strip():
        command.extend(["--download-root", settings.local_asr_download_root.strip()])
    return command


def _pcm16_to_wav(audio_bytes: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(max(1, channels))
        wav_file.setsampwidth(2)
        wav_file.setframerate(max(8000, sample_rate))
        wav_file.writeframes(audio_bytes)
    return buffer.getvalue()
