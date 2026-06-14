# MODVII Claude Access Guide

This file is for Claude or any second agent that needs to run MODVII from the
same Windows machine without guessing paths or accidentally testing an old build.

## Current Project Location

- Windows path: `D:\assist ai`
- WSL-style path, if a tool displays it: `/mnt/d/assist ai`
- GitHub repo: `https://github.com/KecenLi/astralive`
- Default branch: `main`

Do not use stale portable temp folders under:

- `C:\Users\YHT\AppData\Local\Temp\3F*`

Those are Electron portable extraction folders and may contain old code.

## Current Local Model / Cache Layout

- Whisper `large-v3`: `D:\assist ai\models\whisper\large-v3.pt`
- Compatibility junction: `C:\Users\YHT\.cache\whisper` -> `D:\assist ai\models\whisper`
- CosyVoice model: `D:\assist ai\models\Fun-CosyVoice3-0.5B`
- CosyVoice repo/venv: `D:\assist ai\third_party\CosyVoice`
- Project cache root: `D:\assist ai\.cache`

The ignored local `.env` should use:

```powershell
ASR_PROVIDER=local_whisper
LOCAL_ASR_MODEL=large-v3
LOCAL_ASR_DEVICE=cuda
LOCAL_ASR_MODEL_PATH=D:\assist ai\models\whisper\large-v3.pt
TTS_PROVIDER=cosyvoice3
COSYVOICE3_DEVICE=cuda
REALTIME_PROVIDER=none
GPU_SERIALIZE_LOCAL_AUDIO=true
DIALOGUE_TURN_MAX_SECONDS=75
```

Do not commit `.env`, model files, venvs, `data/logs`, or `data/cache`.

## Clean Preflight Before Real UI Testing

Run this if results look suspicious or if an old app may still be running:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    (($_.Name -match '^(MODVII|modvii-server|python|node)') -and ($_.CommandLine -like '*D:\assist ai*')) -or
    ($_.CommandLine -like '*AppData\Local\Temp\3F*MODVII*')
  } |
  Select-Object ProcessId,Name,CommandLine
```

Stop only project-related processes:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    (($_.Name -match '^(MODVII|modvii-server|python|node)') -and ($_.CommandLine -like '*D:\assist ai*')) -or
    ($_.CommandLine -like '*AppData\Local\Temp\3F*MODVII*')
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

Check free GPU memory:

```powershell
nvidia-smi
```

## Start The Real Dev Desktop App

Use the dev launcher when validating Claude's source changes. It starts Vite and
Electron from the current source tree. Electron starts its own backend on a free
port, so do not start another backend manually.

Run from a PowerShell terminal where Node.js/Corepack is available:

```powershell
cd "D:\assist ai"
powershell -ExecutionPolicy Bypass -File scripts\blind-dev-app.ps1
```

Expected behavior:

- One PowerShell window starts Vite at `http://127.0.0.1:5173`.
- One PowerShell window starts Electron.
- The MODVII desktop window appears after the backend health check and local
  model loading. First startup can take 30-60 seconds.
- Grant microphone, camera, and screen permissions when prompted.

The launcher uses `scripts\common.ps1` / `Invoke-Pnpm`, so it can fall back to
`corepack pnpm` when no global `pnpm.cmd` is on PATH.

## Logs To Watch

Main desktop log:

```powershell
Get-Content "$env:APPDATA\modvii-desktop\desktop.log" -Tail 200 -Wait
```

Project test and worker logs:

```powershell
Get-ChildItem "D:\assist ai\data\logs" | Sort-Object LastWriteTime -Descending | Select-Object -First 20
Get-Content "D:\assist ai\data\logs\cosyvoice3-worker.err.log" -Tail 120 -Wait
Get-Content "D:\assist ai\data\logs\local-whisper-worker.err.log" -Tail 120 -Wait
```

If the dev server writes logs under the server app folder, also check:

```powershell
Get-ChildItem "D:\assist ai\apps\server\data\logs" -ErrorAction SilentlyContinue
```

Important strings to search:

```powershell
Select-String -Path "$env:APPDATA\modvii-desktop\desktop.log","D:\assist ai\data\logs\*.log" `
  -Pattern "tts_failed","dialogue_timeout","CosyVoice3 worker","CUDA out of memory","RESOURCE_EXHAUSTED","vision provider failed"
```

## Automated Checks

Backend unit and lint:

```powershell
cd "D:\assist ai\apps\server"
.\.venv\Scripts\python.exe -m pytest app\tests -q
.\.venv\Scripts\python.exe -m ruff check app
```

Local ASR path and model check:

```powershell
cd "D:\assist ai"
powershell -ExecutionPolicy Bypass -File scripts\verify-local-asr.ps1 -SkipDependencySync
```

Desktop interaction smoke, when it is acceptable to kill existing MODVII
processes:

```powershell
cd "D:\assist ai"
$env:MODVII_DESKTOP_EXE="D:\assist ai\dist\desktop\MODVII-0.1.0-asr-largev3-20260614-1754.exe"
node scripts\verify-desktop-interaction.mjs
```

The smoke script kills existing MODVII processes. Do not run it while the user is
actively testing in the GUI unless they approve.

## Blind Soak Script

Claude's independent blind soak script is currently:

```powershell
D:\assist ai\scripts\blind_soak.py
```

Typical usage against a running backend:

```powershell
cd "D:\assist ai"
.\apps\server\.venv\Scripts\python.exe scripts\blind_soak.py --host 127.0.0.1 --port <backend-port> --rounds 12 --noise 0.06
```

If running through `scripts\blind-dev-app.ps1`, first identify the backend port
from `desktop.log`:

```powershell
Select-String "$env:APPDATA\modvii-desktop\desktop.log" -Pattern "backendUrl"
```

Then pass that port to `blind_soak.py`.

## Manual Human-In-The-Loop Test Script

After launching `scripts\blind-dev-app.ps1`, run these checks in the visible UI:

1. Wake MODVII with the button and by saying "小七".
2. Speak a short request with background noise present.
3. Confirm the UI returns to listening automatically after the answer.
4. Toggle camera on/off and request "你看到什么？".
5. Toggle screen capture on/off and request "描述屏幕。".
6. Interrupt while MODVII is speaking, then immediately speak a new request.
7. Repeat at least 10-15 rounds while watching logs for `tts_failed`,
   `dialogue_timeout`, `RESOURCE_EXHAUSTED`, and worker crashes.

Pass criteria:

- No stuck `thinking` or `speaking` state.
- `assistant.audio.done` or a clear `error` event appears for every response turn.
- CosyVoice worker does not disappear without retry.
- ASR/TTS do not overlap into CUDA OOM when `GPU_SERIALIZE_LOCAL_AUDIO=true`.
- Vision either returns `vision.summary`, `vision.need_focus`, or visible
  `vision.error`; it should not fail silently.

## Current Fixes To Validate

Claude's latest source changes are expected to cover:

- CosyVoice worker survives CUDA OOM by clearing CUDA cache and returning a clean
  error instead of process death.
- CosyVoice provider retries once if the worker really crashes.
- ASR and TTS share a process-global GPU lock when local Whisper and CosyVoice
  are both active on CUDA.
- Dialogue turns have a `DIALOGUE_TURN_MAX_SECONDS` watchdog and return to
  listening instead of wedging forever.

Agent 0 read the code and ran:

```text
backend pytest: 88 passed, 2 warnings
backend ruff: All checks passed
scripts\blind-dev-app.ps1: PowerShell parser ok
```

## Git Hygiene

Before editing, run:

```powershell
cd "D:\assist ai"
git status --short
```

At the time this guide was written, Claude had uncommitted source changes in:

- `apps/server/app/api/websocket.py`
- `apps/server/app/config.py`
- `apps/server/app/providers/tts/cosyvoice3.py`
- `apps/server/app/services/audio_service.py`
- `scripts/cosyvoice3_worker.py`

And untracked scripts:

- `scripts/blind-dev-app.ps1`
- `scripts/blind_soak.py`

Do not overwrite another agent's changes. Stage only the files that belong to
the current task.
