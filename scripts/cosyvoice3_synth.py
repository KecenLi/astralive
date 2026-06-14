import argparse
import json
import os
import random
import sys
import wave
from pathlib import Path


def load_wav_for_cosyvoice(path: str | Path, target_sr: int, min_sr: int = 16000):
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


def patch_cosyvoice_wav_loader() -> None:
    import cosyvoice.cli.frontend as frontend
    import cosyvoice.utils.file_utils as file_utils

    file_utils.load_wav = load_wav_for_cosyvoice
    frontend.load_wav = load_wav_for_cosyvoice


def save_wav_pcm16(path: Path, audio, sample_rate: int) -> None:
    import numpy as np

    mono = audio.detach().cpu().squeeze(0).clamp(-1.0, 1.0).numpy()
    pcm = (mono * 32767.0).astype(np.dtype("<i2"), copy=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description="MODVII CosyVoice3 WAV synthesis bridge.")
    parser.add_argument("--input", required=True, help="JSON request file.")
    parser.add_argument("--output", required=True, help="Output WAV path.")
    args = parser.parse_args()

    request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    repo_dir = Path(request["repo_dir"]).resolve()
    model_dir = Path(request["model_dir"]).resolve()
    output_path = Path(args.output).resolve()
    prompt_audio = Path(request.get("prompt_audio") or repo_dir / "asset" / "zero_shot_prompt.wav")
    prompt_text = request.get("prompt_text") or (
        "You are MODVII, a warm and lively bilingual desktop companion.<|endofprompt|>"
        "希望你以后能够做的比我还好呦。"
    )
    device = str(request.get("device") or "cpu").lower()
    seed = int(request.get("seed") or 7327)
    text = str(request.get("text") or "").strip()
    if not text:
        raise ValueError("No text was provided for CosyVoice3 synthesis.")
    if not prompt_audio.exists():
        raise FileNotFoundError(
            f"Prompt audio not found: {prompt_audio}. Set COSYVOICE3_PROMPT_AUDIO or keep "
            "CosyVoice/asset/zero_shot_prompt.wav available."
        )

    if device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    sys.path.insert(0, str(repo_dir))
    sys.path.insert(0, str(repo_dir / "third_party" / "Matcha-TTS"))

    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    patch_cosyvoice_wav_loader()

    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    model = AutoModel(model_dir=str(model_dir))
    chunks = [
        chunk["tts_speech"].detach().cpu()
        for chunk in model.inference_zero_shot(text, prompt_text, str(prompt_audio), stream=False)
        if "tts_speech" in chunk
    ]
    if not chunks:
        raise RuntimeError("CosyVoice3 returned no tts_speech chunks.")
    audio = (torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]).clamp(-1.0, 1.0)
    save_wav_pcm16(output_path, audio, model.sample_rate)
    print(json.dumps({"sample_rate": model.sample_rate, "chunks": len(chunks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
