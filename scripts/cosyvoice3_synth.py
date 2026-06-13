import argparse
import json
import os
import sys
from pathlib import Path


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
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    model = AutoModel(model_dir=str(model_dir))
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
    print(json.dumps({"sample_rate": model.sample_rate, "chunks": len(chunks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
