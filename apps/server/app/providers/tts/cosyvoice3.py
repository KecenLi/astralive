import asyncio
import base64
import json
import os
import sys
import uuid
import wave
from pathlib import Path

from app.config import Settings
from app.contracts.model_io import TTSInput, TTSResult
from app.providers.tts.base import TTSProvider


class CosyVoice3TTSProvider(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._worker: _CosyVoice3Worker | None = None

    async def synthesize(self, data: TTSInput) -> TTSResult:
        if not data.text.strip():
            return TTSResult(mime="audio/wav", encoding="wav", raw={"provider": "cosyvoice3"})

        script = Path(self.settings.cosyvoice3_script)
        if not script.exists():
            raise RuntimeError(f"CosyVoice3 synthesis script not found: {script}")

        repo_dir = Path(self.settings.cosyvoice3_repo_dir)
        model_dir = Path(self.settings.cosyvoice3_model_dir)
        if not repo_dir.exists():
            raise RuntimeError(f"CosyVoice3 repo not found: {repo_dir}. Run scripts/setup-cosyvoice3.ps1.")
        if not model_dir.exists():
            raise RuntimeError(f"CosyVoice3 model not found: {model_dir}. Run scripts/setup-cosyvoice3.ps1.")

        output_dir = self.settings.data_dir / "cache" / "tts"
        output_dir.mkdir(parents=True, exist_ok=True)
        request_id = uuid.uuid4().hex
        input_path = output_dir / f"cosyvoice3-{request_id}.json"
        output_path = output_dir / f"cosyvoice3-{request_id}.wav"
        request = {
            "text": data.text,
            "voice": data.voice,
            "emotion": data.emotion,
            "repo_dir": str(repo_dir),
            "model_dir": str(model_dir),
            "prompt_audio": self.settings.cosyvoice3_prompt_audio,
            "prompt_text": self.settings.cosyvoice3_prompt_text,
            "device": self.settings.cosyvoice3_device,
        }
        input_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

        try:
            if self.settings.cosyvoice3_worker_enabled:
                await self._run_worker_script(input_path, output_path)
            else:
                await self._run_synth_script(input_path, output_path)
            audio_bytes = output_path.read_bytes()
            sample_rate, channels, duration_ms = _wav_metadata(output_path)
            return TTSResult(
                audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
                mime="audio/wav",
                sample_rate=sample_rate,
                channels=channels,
                encoding="wav",
                duration_ms=duration_ms,
                raw={"provider": "cosyvoice3", "model": str(model_dir), "voice": data.voice},
            )
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    async def _run_worker_script(self, input_path: Path, output_path: Path) -> None:
        if self._worker is None:
            self._worker = _CosyVoice3Worker(self.settings)
        request = json.loads(input_path.read_text(encoding="utf-8"))
        await self._worker.synthesize(request, output_path)

    async def _run_synth_script(self, input_path: Path, output_path: Path) -> None:
        python = self.settings.cosyvoice3_python or sys.executable
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        process = await asyncio.create_subprocess_exec(
            python,
            str(self.settings.cosyvoice3_script),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(1.0, self.settings.cosyvoice3_timeout_seconds),
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("CosyVoice3 synthesis timed out.") from exc

        if process.returncode != 0:
            details = (stderr or stdout).decode("utf-8", errors="replace")[-2000:].strip()
            raise RuntimeError(f"CosyVoice3 synthesis failed: {details}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            details = stdout.decode("utf-8", errors="replace")[-1000:].strip()
            raise RuntimeError(f"CosyVoice3 synthesis produced no audio. {details}")


class _CosyVoice3Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.stderr_file = None

    async def synthesize(self, request: dict, output_path: Path) -> None:
        async with self.lock:
            process = await self._ensure_process()
            request_id = uuid.uuid4().hex
            payload = {
                **request,
                "id": request_id,
                "output": str(output_path),
            }
            if not process.stdin or not process.stdout:
                raise RuntimeError("CosyVoice3 worker pipes are not available.")
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()
            started = asyncio.get_running_loop().time()
            while True:
                remaining = self.settings.cosyvoice3_timeout_seconds - (asyncio.get_running_loop().time() - started)
                if remaining <= 0:
                    self._terminate()
                    raise RuntimeError("CosyVoice3 worker synthesis timed out.")
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                except TimeoutError as exc:
                    self._terminate()
                    raise RuntimeError("CosyVoice3 worker synthesis timed out.") from exc
                if not line:
                    code = process.returncode
                    self._terminate()
                    raise RuntimeError(f"CosyVoice3 worker exited before returning audio. exit_code={code}")
                response = json.loads(line.decode("utf-8"))
                if str(response.get("id") or "") != request_id:
                    continue
                if not response.get("ok"):
                    raise RuntimeError(f"CosyVoice3 worker failed: {response.get('error')}")
                if not output_path.exists() or output_path.stat().st_size == 0:
                    raise RuntimeError("CosyVoice3 worker produced no audio.")
                return

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self.process and self.process.returncode is None:
            return self.process

        script = Path(self.settings.cosyvoice3_worker_script)
        if not script.exists():
            raise RuntimeError(f"CosyVoice3 worker script not found: {script}")
        python = self.settings.cosyvoice3_python or sys.executable
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.settings.logs_dir / "cosyvoice3-worker.err.log"
        self.stderr_file = log_path.open("ab")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self.process = await asyncio.create_subprocess_exec(
            python,
            str(script),
            "--repo-dir",
            str(self.settings.cosyvoice3_repo_dir),
            "--model-dir",
            str(self.settings.cosyvoice3_model_dir),
            "--device",
            str(self.settings.cosyvoice3_device),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self.stderr_file,
            env=env,
        )
        return self.process

    def _terminate(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.kill()
        self.process = None
        if self.stderr_file:
            self.stderr_file.close()
            self.stderr_file = None


def _wav_metadata(path: Path) -> tuple[int, int, int | None]:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        frames = wav.getnframes()
    duration_ms = int((frames / sample_rate) * 1000) if sample_rate > 0 else None
    return sample_rate, channels, duration_ms
