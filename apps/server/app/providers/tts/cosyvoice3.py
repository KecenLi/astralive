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


def _wav_metadata(path: Path) -> tuple[int, int, int | None]:
    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        frames = wav.getnframes()
    duration_ms = int((frames / sample_rate) * 1000) if sample_rate > 0 else None
    return sample_rate, channels, duration_ms
