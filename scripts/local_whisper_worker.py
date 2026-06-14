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


# Priming text steers Whisper toward Simplified Chinese with punctuation and the
# assistant's own vocabulary, which markedly cuts homophone errors and wrong
# characters on short spoken turns. The assistant name "小七" is included so it
# is transcribed correctly instead of homophones like 小柒/小气/小七.
CHINESE_INITIAL_PROMPT = (
    "以下是普通话对话的转写，使用简体中文并保留标点符号。"
    "用户在和桌面语音助手小七聊天，内容涉及日常交流、屏幕与摄像头里看到的东西、提问和闲聊。"
    "常见术语包括：视觉摘要、摄像头摘要、屏幕摘要、融合摘要、屏幕捕捉、摄像头画面、Live2D。"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="MODVII persistent local Whisper ASR worker.")
    parser.add_argument("--model", default="base")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--download-root", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Guarantee UTF-8 stdio regardless of how the worker was launched, so Chinese
    # transcripts are never mangled by a non-UTF-8 console code page on Windows.
    for stream in (sys.stdout, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")
    ensure_ffmpeg_on_path()
    import whisper

    model_target = args.model
    download_root = args.download_root.strip() or None
    model_path = args.model_path.strip()
    if model_path:
        resolved_model_path = Path(model_path).expanduser().resolve()
        if not resolved_model_path.exists():
            raise FileNotFoundError(f"Local Whisper model file not found: {resolved_model_path}")
        model_target = str(resolved_model_path)
        download_root = None

    model = whisper.load_model(model_target, device=args.device, download_root=download_root)
    default_language = normalize_language(args.language)

    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id") or "")
            audio_path = Path(request["audio_path"]).resolve()
            language = normalize_language(str(request.get("language") or "")) or default_language
            on_gpu = str(args.device).lower().startswith("cuda")
            # Use the Chinese priming prompt only for Chinese (or auto) turns so it
            # does not bias English transcription. A per-request override wins.
            request_prompt = str(request.get("initial_prompt") or "").strip()
            if request_prompt:
                initial_prompt: str | None = request_prompt
            elif language in (None, "zh"):
                initial_prompt = CHINESE_INITIAL_PROMPT
            else:
                initial_prompt = None
            result = model.transcribe(
                str(audio_path),
                language=language,
                task="transcribe",
                fp16=on_gpu,
                verbose=False,
                # Beam search is more accurate than greedy decoding; affordable on
                # GPU. Falls back gracefully on CPU (just slower).
                beam_size=5 if on_gpu else None,
                initial_prompt=initial_prompt,
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
