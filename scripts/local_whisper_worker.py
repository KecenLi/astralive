import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def normalize_language(value: str) -> str | None:
    normalized = (value or "").strip().lower().replace("_", "-")
    if not normalized or normalized in {"auto", "none"}:
        return None
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return normalized.split("-", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="MODVII persistent local Whisper ASR worker.")
    parser.add_argument("--model", default="base")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    ensure_ffmpeg_on_path()
    import whisper

    model = whisper.load_model(args.model, device=args.device)
    default_language = normalize_language(args.language)

    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id") or "")
            audio_path = Path(request["audio_path"]).resolve()
            language = normalize_language(str(request.get("language") or "")) or default_language
            result = model.transcribe(
                str(audio_path),
                language=language,
                task="transcribe",
                fp16=str(args.device).lower().startswith("cuda"),
                verbose=False,
                condition_on_previous_text=False,
                no_speech_threshold=0.72,
                logprob_threshold=-1.2,
                compression_ratio_threshold=2.4,
            )
            text = str(result.get("text") or "").strip()
            response = {
                "id": request_id,
                "ok": True,
                "text": text,
                "language": result.get("language"),
                "segments": len(result.get("segments") or []),
            }
        except Exception as exc:  # noqa: BLE001
            response = {"id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def ensure_ffmpeg_on_path() -> None:
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg

        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    except Exception:
        return
    if ffmpeg.exists():
        shim_dir = Path(tempfile.gettempdir()) / "modvii-ffmpeg"
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim = shim_dir / "ffmpeg.exe"
        if not shim.exists() or shim.stat().st_size != ffmpeg.stat().st_size:
            shutil.copy2(ffmpeg, shim)
        os.environ["PATH"] = f"{shim_dir}{os.pathsep}{ffmpeg.parent}{os.pathsep}{os.environ.get('PATH', '')}"


if __name__ == "__main__":
    raise SystemExit(main())
