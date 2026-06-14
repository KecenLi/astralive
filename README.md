# MODVII

MODVII, also called Xiaoqi / 小七, is a Windows desktop AI companion built as a
practical MVP: an Electron shell, a React interface, a FastAPI backend, webcam
and screen perception, wake-word style voice input, local ASR/TTS options,
Vertex/Gemini-compatible cloud providers, cost telemetry, and a Live2D desktop
pet.

This repository is intended to be reproducible from GitHub. The default Live2D
portrait is now Lisette, included under `apps/web/public/live2d/lisette`, so a
fresh clone can build the UI with the configured avatar. The official Live2D
sample Haru is also included as the safer public/commercial fallback. Large
model weights, local secrets, logs, packaged executables, and locally downloaded
third-party source trees are not committed; scripts below reproduce them.

## Current MVP Scope

- Windows desktop target.
- Electron main/preload starts and owns the packaged backend.
- React UI for microphone, camera, screen capture, settings, cost telemetry, and
  conversation.
- Transparent desktop pet window with Live2D rendering.
- Default Live2D model: **Lisette**.
- Safer fallback Live2D model: official Live2D sample **Haru**.
- Lisette is included for this personal/non-commercial MVP configuration, but
  it carries redistribution and commercial-use risk. Use Haru for commercial,
  enterprise, or permission-sensitive builds.
- Voice input with browser media capture, TEN VAD, streaming chunks, and local
  Whisper ASR.
- Wake word / name: `小七`.
- Local TTS route through Fun-CosyVoice3, with cloud-compatible TTS providers as
  alternatives.
- Vertex AI / Gemini-compatible LLM and vision providers.
- Camera summary, screen summary, and fused visual summary are stored and shown
  separately.
- Visual upload cost controls: low-fps mode, continuous sampled mode, scene
  hash dedupe, cooldowns, voice-priority scheduling, and cost estimates.
- Prompt-safety checks for common prompt-injection and secret-exfiltration
  attempts.

## Repository Layout

```text
.
├─ apps/
│  ├─ desktop/              Electron main/preload and electron-builder config
│  ├─ server/               FastAPI backend, provider registry, tests
│  └─ web/                  React UI, Live2D, media capture, VAD, state
├─ apps/web/public/live2d/  Public Live2D assets committed for default avatar
├─ apps/web/public/vendor/  Browser-side runtime assets: Cubism core, VAD, ONNX
├─ packages/contracts/      Shared event schema
├─ scripts/                 Setup, build, package, model, and verification tools
├─ .env.example             Safe environment template
└─ README.md                This public reproduction guide
```

Ignored local-only paths include `.env`, `data/`, `dist/`, `models/`,
`third_party/`, `.installers/`, virtual environments, build output, and internal
work notes.

## Required Host Tools

Use Windows 10/11 with PowerShell. WSL is not required.

Install:

- Git for Windows.
- Node.js 20 or newer.
- Corepack / pnpm. The workspace uses `pnpm@9.15.4`.
- Python 3.11 or newer for the backend.
- `uv` for Python dependency management. It is strongly recommended because the
  scripts expect `uv.exe` when available.
- Google Cloud CLI if using Vertex AI / ADC.
- Optional: NVIDIA GPU + CUDA-capable PyTorch for local Whisper/CosyVoice.
- Optional: Ollama for fully local LLM experiments.

Recommended one-time shell setup:

```powershell
corepack enable
corepack prepare pnpm@9.15.4 --activate
python --version
uv --version
```

## Fresh Clone Quick Start

```powershell
git clone https://github.com/KecenLi/astralive.git "D:\assist ai"
cd "D:\assist ai"

pnpm install
cd apps\server
uv sync --group dev
cd ..\..

Copy-Item .env.example .env
```

Start dev mode:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 all
```

If you want to run the web and desktop windows manually:

```powershell
# Terminal 1
cd "D:\assist ai"
pnpm --filter "@modvii/web" dev

# Terminal 2
cd "D:\assist ai"
pnpm --filter modvii-desktop dev
```

The default `.env.example` uses mock providers, so the UI can start without API
keys. Real voice/vision/LLM routes need the provider configuration below.

## Live2D Avatar Assets

The repo includes the configured default Live2D portrait:

```text
apps/web/public/live2d/lisette/Lisette.model3.json
```

The default model URL is:

```dotenv
VITE_LIVE2D_MODEL_URL=./live2d/lisette/Lisette.model3.json
```

### Lisette License And Redistribution Risk

Lisette is bundled to match the current MODVII MVP configuration. It has a
richer expression/motion set than Haru and includes:

- full-body expression toggles such as angry, frenzy, sad, shy, tear, and
  tongue-out;
- idle and breathing motions;
- greeting, happy, sad, frenzy, jump, walk, run, and other animation groups;
- a `ParamMouthOpenY` lip-sync group configured for MODVII.

Risk statement:

- The model `READ_ME.txt` states: "Do not use this model for commercial
  purposes!"
- The model credits Lisette from *Pocket Mirror*, AstralShift, and the Live2D
  rigger/animator shiranui_bzw.
- This repo includes the model for personal/non-commercial reproduction of this
  MVP. That does not remove copyright, character-IP, platform, or redistribution
  risk.
- Do not use the Lisette bundle for commercial, enterprise, client, marketplace,
  or public distribution builds unless you have explicit permission from the
  relevant rights holders.
- For safer public/commercial builds, switch to Haru:

```dotenv
VITE_LIVE2D_MODEL_URL=./live2d/haru/haru/runtime/haru.model3.json
```

Lisette local asset path:

```text
apps/web/public/live2d/lisette/Lisette.model3.json
```

Lisette source/credit files are retained in the model folder, including:

```text
apps/web/public/live2d/lisette/READ_ME.txt
apps/web/public/live2d/lisette/Lisette.model3.json
apps/web/public/live2d/lisette/Lisette.vtube.json
```

### Haru Fallback

Haru remains committed as the lower-risk fallback:

```text
apps/web/public/live2d/haru/haru/runtime/haru.model3.json
```

Haru is official Live2D sample data. Required notice:

> This content uses sample data owned and copyrighted by Live2D Inc. The sample
> data are utilized in accordance with terms and conditions set by Live2D Inc.
> This content itself is created at the author’s sole discretion.

References:

- Live2D Sample Data: https://www.live2d.com/en/learn/sample/
- Live2D Free Material License: https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html
- Live2D Sample Data Terms: https://www.live2d.com/en/learn/sample/model-terms/

The browser Cubism runtime file is committed at:

```text
apps/web/public/vendor/live2dcubismcore.min.js
```

The old local Lisette installer remains for refreshing the bundled files from a
locally downloaded zip:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-lisette-live2d.ps1 -AcceptNonCommercialTerms
```

## Environment Configuration

Copy `.env.example` to `.env`, then edit local secrets and provider choices.

Important provider variables:

```dotenv
ASR_PROVIDER=mock
VISION_PROVIDER=mock
LLM_PROVIDER=mock
TTS_PROVIDER=mock
REALTIME_PROVIDER=none
WAKE_WORD=小七
PERSONA_PROMPT=你是 MODVII，也叫小七，一个中文优先的女性 AI VTuber 桌面伴侣。回答要适合语音朗读，保持简短、自然、具体。
```

Provider choices implemented in the backend:

- ASR: `mock`, `local_whisper`, `google_genai`, `openai_compatible`.
- Vision: `mock`, `vertex_ai`, `openai_compatible`.
- LLM: `mock`, `vertex_ai`, `openai_compatible`, `ollama`.
- TTS: `mock`, `cosyvoice3`, `google_genai`, `openai_compatible`.
- Realtime: `none`, `mock`, `google_genai_live`.

## Vertex AI / Google Cloud Setup

Use ADC for local development:

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Then set `.env`:

```dotenv
ASR_PROVIDER=local_whisper
VISION_PROVIDER=vertex_ai
LLM_PROVIDER=vertex_ai
TTS_PROVIDER=cosyvoice3
REALTIME_PROVIDER=none

VERTEX_AI_PROJECT=YOUR_PROJECT_ID
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_API_ENDPOINT=https://aiplatform.googleapis.com
VERTEX_AI_LLM_MODEL=gemini-2.5-flash
VERTEX_AI_VISION_MODEL=gemini-2.5-flash
VERTEX_AI_REQUEST_TIMEOUT_SECONDS=35
```

If your project uses a service-account JSON instead of user ADC:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
```

Do not commit `.env` or credentials.

## OpenAI-Compatible / Gemini-Compatible Providers

LLM and vision can use OpenAI-compatible endpoints:

```dotenv
LLM_PROVIDER=openai_compatible
VISION_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=https://example.com/v1
OPENAI_COMPATIBLE_API_KEY=YOUR_KEY
OPENAI_COMPATIBLE_LLM_MODEL=MODEL_NAME
OPENAI_COMPATIBLE_VISION_MODEL=VISION_MODEL_NAME
```

ASR OpenAI-compatible route:

```dotenv
ASR_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_ASR_BASE_URL=https://example.com/v1
OPENAI_COMPATIBLE_ASR_API_KEY=YOUR_KEY
OPENAI_COMPATIBLE_ASR_MODEL=whisper-1
OPENAI_COMPATIBLE_ASR_ENDPOINT_PATH=/audio/transcriptions
```

TTS OpenAI-compatible route:

```dotenv
TTS_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_TTS_BASE_URL=https://example.com/v1
OPENAI_COMPATIBLE_TTS_API_KEY=YOUR_KEY
OPENAI_COMPATIBLE_TTS_MODEL=tts-1
OPENAI_COMPATIBLE_TTS_VOICE=default
OPENAI_COMPATIBLE_TTS_ENDPOINT_PATH=/audio/speech
OPENAI_COMPATIBLE_TTS_RESPONSE_FORMAT=mp3
```

`scripts\configure-china-provider.ps1` is provided as a starting point for
domestic API routes. Fill provider keys locally; do not commit them.

## Local ASR: Whisper

Default local ASR worker:

```dotenv
ASR_PROVIDER=local_whisper
LOCAL_ASR_WORKER_SCRIPT=scripts/local_whisper_worker.py
LOCAL_ASR_MODEL=base
LOCAL_ASR_MODEL_PATH=
LOCAL_ASR_DOWNLOAD_ROOT=
LOCAL_ASR_DEVICE=cpu
LOCAL_ASR_TIMEOUT_SECONDS=120
AUDIO_TRANSCRIPTION_LANGUAGE=zh-CN
```

For GPU:

```dotenv
LOCAL_ASR_DEVICE=cuda
```

For reproducible model storage outside C drive:

```dotenv
LOCAL_ASR_MODEL_PATH=D:\assist ai\models\whisper\base.pt
```

The worker uses `openai-whisper`. The easiest path is to use the CosyVoice setup
script below, which installs Whisper into the same Python environment and writes
the `LOCAL_ASR_PYTHON` path. You can also install Whisper yourself in a dedicated
Python environment and set:

```dotenv
LOCAL_ASR_PYTHON=C:\path\to\python.exe
```

Quality note: `base` is the deadline/default speed model. It is fast and light,
but it can make Chinese homophone mistakes under noise. For maximum ASR accuracy,
use `large-v3` or test SenseVoice/FunASR/Sherpa-ONNX as a local endpoint.

## Local TTS: Fun-CosyVoice3

MODVII supports local TTS through `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`.

Install on Windows:

```powershell
cd "D:\assist ai"
powershell -ExecutionPolicy Bypass -File scripts\setup-cosyvoice3.ps1
```

This script:

- clones `FunAudioLLM/CosyVoice` into ignored `third_party\CosyVoice`;
- creates a Python 3.10 virtual environment;
- installs CosyVoice dependencies;
- installs `openai-whisper` and `imageio-ffmpeg`;
- downloads `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` into ignored `models\`;
- writes local `.env` entries for `TTS_PROVIDER=cosyvoice3` and
  `ASR_PROVIDER=local_whisper`.

For RTX 50 / Blackwell class GPUs, use CUDA 12.8 PyTorch wheels:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-cosyvoice3.ps1 `
  -TorchIndexUrl "https://download.pytorch.org/whl/cu128" `
  -Device cuda
```

Key `.env` entries:

```dotenv
TTS_PROVIDER=cosyvoice3
COSYVOICE3_PYTHON=D:\assist ai\third_party\CosyVoice\.venv\Scripts\python.exe
COSYVOICE3_REPO_DIR=D:\assist ai\third_party\CosyVoice
COSYVOICE3_MODEL_DIR=D:\assist ai\models\Fun-CosyVoice3-0.5B
COSYVOICE3_SCRIPT=D:\assist ai\scripts\cosyvoice3_synth.py
COSYVOICE3_WORKER_ENABLED=true
COSYVOICE3_WORKER_SCRIPT=D:\assist ai\scripts\cosyvoice3_worker.py
COSYVOICE3_PROMPT_AUDIO=D:\assist ai\third_party\CosyVoice\asset\zero_shot_prompt.wav
COSYVOICE3_DEVICE=cuda
```

CosyVoice3 is expressive but compute-heavy. MODVII serializes local GPU ASR/TTS
work to avoid Whisper and CosyVoice fighting for VRAM.

## Ollama Local LLM

Install Ollama for Windows, then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pull-models.ps1 -Model qwen2.5:0.5b
```

Set `.env`:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_LLM_MODEL=qwen2.5:0.5b
```

This is useful for offline development. Vision still needs a vision-capable
provider unless you use `VISION_PROVIDER=mock`.

## Camera and Screen Perception

MODVII has two visual sources:

- camera summary;
- screen summary;
- fused summary built from both.

The frontend can use:

- low-fps stable mode;
- continuous sampled mode;
- manual/focus capture.

Default visual cost controls:

```dotenv
FRAME_IDLE_FPS=0
FRAME_AWAKE_FPS=0.2
FRAME_ACTIVE_FPS=1
FRAME_JPEG_QUALITY=0.72
MAX_FRAME_WIDTH=1280
MAX_FRAME_HEIGHT=720
VISION_CACHE_TTL_SECONDS=30
VISION_REQUEST_TIMEOUT_SECONDS=35
VISION_MAX_CONCURRENCY=2
VISION_PENDING_FRAME_LIMIT=2
VISION_RESULT_MAX_AGE_SECONDS=35
SCENE_CHANGE_THRESHOLD=0.12
```

The app sends frame metrics even when it skips uploads. Cost telemetry shows
candidate frames, actual calls, cache hits, sleep blocks, cooldown drops, and
estimated visual cost savings.

## Desktop Build and Packaging

Build web and backend:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Package Windows installer and portable exe:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -SkipLive2D
```

`-SkipLive2D` is safe for this repo because Lisette and Haru are committed.
Without the flag, the script may re-download the official Live2D sample.

Output:

```text
dist/desktop/MODVII 0.1.0.exe
dist/desktop/MODVII Setup 0.1.0.exe
dist/desktop/win-unpacked/MODVII.exe
```

Packaged Electron includes:

- compiled desktop shell;
- built React UI;
- packaged FastAPI backend executable;
- worker scripts needed for local ASR/TTS;
- committed Live2D Lisette and Haru assets;
- committed browser-side VAD / ONNX runtime vendor assets.

Large local model weights remain outside the package unless you explicitly place
them in a custom packaging flow. The app reads local `.env` and model paths.

## Verification Commands

Backend:

```powershell
cd "D:\assist ai\apps\server"
$env:PYTHONPATH="."
uv run pytest app/tests -q
uv run ruff check app
```

Frontend:

```powershell
cd "D:\assist ai"
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
```

Desktop smoke:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-desktop-smoke.ps1 -Portable
```

Real-provider desktop smoke:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-desktop-smoke.ps1 `
  -RealApi `
  -Portable `
  -NoiseProfile low_noise `
  -RequestText "小七，请用一句话说明你能看到摄像头和屏幕摘要。"
```

Other useful checks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-local-asr.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-local-tts.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-modvii-adversarial-dialogue.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify-open-llm-vtuber-standards.ps1
```

## Final MVP Package Reference

The MVP package built during the final round was:

```text
D:\assist ai\dist\desktop\MODVII 0.1.0.exe
SHA256 239D02BDD4BF6319ADE41AA29BE671F748B8264A44D93E7FA1C2B838BBA813A4
```

This binary is not committed. Rebuild it locally with `scripts\package.ps1`.

## Security and Privacy

- Do not commit `.env`, API keys, Google credentials, local tokens, logs, or
  model checkpoints.
- Camera, screen, and microphone data are local until the configured provider
  route sends selected frames/audio/text to an API.
- Default mock mode sends nothing to remote providers.
- Visual frame uploads are throttled and deduplicated.
- Prompt-safety service blocks common attempts to reveal hidden prompts, API
  keys, local secret paths, or instruction hierarchy.
- Autostart is user-selected, not silently enabled.

## Third-Party Components

Runtime and libraries:

- Electron, React, Vite, Zustand, Lucide, PixiJS.
- `pixi-live2d-display` for Live2D rendering.
- Live2D Cubism Core runtime redistributable.
- `@ricky0123/vad-web`, `defuss-vad`, `onnxruntime-web`, and committed VAD
  browser assets.
- FastAPI, Uvicorn, Pydantic, HTTPX, google-genai, google-auth.
- PyInstaller for backend packaging.
- Optional local: OpenAI Whisper, CosyVoice, PyTorch, Hugging Face Hub,
  imageio-ffmpeg.
- Optional local LLM: Ollama.

Architecture and implementation references used during development:

- Open-LLM-VTuber: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- Pipecat: https://github.com/pipecat-ai/pipecat
- RealtimeSTT: https://github.com/KoljaB/RealtimeSTT
- FunASR: https://github.com/modelscope/FunASR
- SenseVoice: https://github.com/FunAudioLLM/SenseVoice
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx
- LiteLLM pricing-table concept: https://github.com/BerriAI/litellm
- Gemini cookbook spatial prompting reference:
  https://github.com/google-gemini/cookbook

These references were used for architecture, testing ideas, provider patterns,
prompting conventions, and cost-observability design. MODVII implementation code
uses its own module names and integration logic.

## License

The original MODVII source code in this repository is released under the MIT
License; see `LICENSE`.

Third-party dependencies, browser runtime files, model assets, Live2D assets,
sample data, VAD/ONNX files, and any files retaining upstream notices remain
under their own licenses and terms. In particular, Lisette is included for the
current personal/non-commercial MVP configuration and should not be treated as
MIT-licensed MODVII code.

## Known MVP Limitations

- Windows is the only supported desktop target in this MVP.
- Whisper `base` is fast but not perfect under noisy Chinese speech. It can make
  homophone mistakes.
- CosyVoice3 is high quality but heavy; GPU setup matters.
- Vertex/Gemini quota or regional latency can dominate response time.
- Continuous screen/camera sampling is intentionally sampled and throttled; it is
  not raw 30 fps video upload.
- Lisette is redistributed in this repo for the current personal MVP setup, but
  it is non-commercial and carries copyright/character-IP/redistribution risk.
  Use Haru for commercial, enterprise, marketplace, or permission-sensitive
  builds.

## Clean GitHub Reproduction Checklist

From a new machine:

1. Clone this repo.
2. Install Node 20+, pnpm, Python 3.11+, and uv.
3. Run `pnpm install`.
4. Run `uv sync --group dev` under `apps/server`.
5. Copy `.env.example` to `.env`.
6. Use mock providers for offline UI, or configure Vertex/OpenAI-compatible
   providers for real API behavior.
7. Run `scripts\setup-cosyvoice3.ps1` if local TTS/Whisper ASR is needed.
8. Run `scripts\dev.ps1 all` for development.
9. Run `scripts\package.ps1 -SkipLive2D` for installer/portable output.

The default Live2D Lisette portrait and the Haru fallback are already present in
the GitHub checkout.
