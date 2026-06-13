import argparse
import contextlib
import json
import os
import random
import sys
from pathlib import Path


def load_model(repo_dir: Path, model_dir: Path, device: str):
    if device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

    sys.path.insert(0, str(repo_dir))
    sys.path.insert(0, str(repo_dir / "third_party" / "Matcha-TTS"))

    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import torchaudio
        from cosyvoice.cli.cosyvoice import AutoModel

        model = AutoModel(model_dir=str(model_dir))
    return model, torch, torchaudio


def synthesize(request: dict, model, torch, torchaudio) -> dict:
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

    with contextlib.redirect_stdout(sys.stderr):
        chunks = [
            chunk["tts_speech"].detach().cpu()
            for chunk in model.inference_zero_shot(text, prompt_text, str(prompt_audio), stream=False)
            if "tts_speech" in chunk
        ]
    if not chunks:
        raise RuntimeError("CosyVoice3 returned no tts_speech chunks.")

    audio = (torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]).clamp(-1.0, 1.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(
        str(output_path),
        audio,
        model.sample_rate,
        encoding="PCM_S",
        bits_per_sample=16,
    )
    return {"sample_rate": model.sample_rate, "chunks": len(chunks)}


def main() -> int:
    parser = argparse.ArgumentParser(description="MODVII persistent CosyVoice3 worker.")
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    protocol_stdout = sys.stdout
    repo_dir = Path(args.repo_dir).resolve()
    model_dir = Path(args.model_dir).resolve()
    model, torch, torchaudio = load_model(repo_dir, model_dir, str(args.device or "cpu").lower())

    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id") or "")
            result = synthesize(request, model, torch, torchaudio)
            response = {"id": request_id, "ok": True, **result}
        except Exception as exc:  # noqa: BLE001
            response = {"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), file=protocol_stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
