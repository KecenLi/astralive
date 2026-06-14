import argparse
import contextlib
import json
import os
import random
import sys
import wave
from pathlib import Path


def _load_wav_for_cosyvoice(path: str | Path, target_sr: int, min_sr: int = 16000):
    import numpy as np
    import torch
    import torchaudio.functional as torchaudio_functional

    path = Path(path)
    try:
        import soundfile as sf

        speech, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        speech = speech.mean(axis=1)
    except Exception:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            frames = wav.readframes(frame_count)

        if sample_width != 2:
            raise ValueError(f"CosyVoice3 prompt audio must be readable WAV audio: {path}")
        speech = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
        if channels > 1:
            speech = speech.reshape(-1, channels).mean(axis=1)
    if sample_rate < min_sr:
        raise ValueError(f"CosyVoice3 prompt audio sample rate {sample_rate} must be at least {min_sr}: {path}")

    speech_tensor = torch.from_numpy(np.asarray(speech, dtype="float32")).unsqueeze(0)
    if sample_rate != target_sr:
        speech_tensor = torchaudio_functional.resample(speech_tensor, sample_rate, target_sr)
    return speech_tensor


def _patch_cosyvoice_wav_loader() -> None:
    import cosyvoice.cli.frontend as frontend
    import cosyvoice.utils.file_utils as file_utils

    file_utils.load_wav = _load_wav_for_cosyvoice
    frontend.load_wav = _load_wav_for_cosyvoice


def _save_wav_pcm16(path: Path, audio, sample_rate: int) -> None:
    import numpy as np

    mono = audio.detach().cpu().squeeze(0).clamp(-1.0, 1.0).numpy()
    pcm = (mono * 32767.0).astype(np.dtype("<i2"), copy=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def load_model(repo_dir: Path, model_dir: Path, device: str):
    if device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    sys.path.insert(0, str(repo_dir))
    sys.path.insert(0, str(repo_dir / "third_party" / "Matcha-TTS"))

    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from cosyvoice.cli.cosyvoice import AutoModel

        _patch_cosyvoice_wav_loader()
        model = AutoModel(model_dir=str(model_dir))
    return model, torch


def synthesize(request: dict, model, torch) -> dict:
    text = str(request.get("text") or "").strip()
    if not text:
        raise ValueError("No text was provided for CosyVoice3 synthesis.")

    output_path = Path(request["output"]).resolve()
    prompt_audio = Path(request["prompt_audio"]).resolve()
    prompt_text = str(request.get("prompt_text") or "")
    seed = int(request.get("seed") or 7327)
    if not prompt_audio.exists():
        raise FileNotFoundError(f"Prompt audio not found: {prompt_audio}")

    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    try:
        with contextlib.redirect_stdout(sys.stderr):
            chunks = [
                chunk["tts_speech"].detach().cpu()
                for chunk in model.inference_zero_shot(text, prompt_text, str(prompt_audio), stream=False)
                if "tts_speech" in chunk
            ]
    except RuntimeError as exc:
        # A CUDA out-of-memory mid-inference would otherwise corrupt the CUDA
        # context and kill the whole worker process (exit_code=None on the
        # provider side). Instead, free cached VRAM and surface a normal error
        # response so the worker stays alive for the next request.
        if _is_cuda_oom(exc):
            _free_cuda(torch)
            raise RuntimeError(f"CUDA out of memory during synthesis; recovered worker. {exc}") from exc
        raise
    if not chunks:
        raise RuntimeError("CosyVoice3 returned no tts_speech chunks.")

    audio = (torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]).clamp(-1.0, 1.0)
    _save_wav_pcm16(output_path, audio, model.sample_rate)
    # Proactively release the activation memory so back-to-back turns under GPU
    # pressure (ASR + TTS sharing one card) don't accumulate toward an OOM.
    _free_cuda(torch)
    return {"sample_rate": model.sample_rate, "chunks": len(chunks)}


def _is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda error" in message or "cublas" in message


def _free_cuda(torch) -> None:
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:  # noqa: BLE001 - best-effort cleanup, never fatal
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="MODVII persistent CosyVoice3 worker.")
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    protocol_stdout = sys.stdout
    repo_dir = Path(args.repo_dir).resolve()
    model_dir = Path(args.model_dir).resolve()
    model, torch = load_model(repo_dir, model_dir, str(args.device or "cpu").lower())

    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id") or "")
            result = synthesize(request, model, torch)
            response = {"id": request_id, "ok": True, **result}
        except Exception as exc:  # noqa: BLE001
            response = {"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), file=protocol_stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
