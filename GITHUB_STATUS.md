# MODVII GitHub Status

- Repository: https://github.com/KecenLi/astralive
- Branch: main
- Latest feature commit for this round: `db6d261` (`Fix visual capture contention and continuous listening`)
- To check the current latest commit: `git rev-parse --short HEAD`
- Reminder: after each implementation and test round, commit and push intentional source changes, then report the commit hash, latest packaged exe path, timestamp, and SHA256.

## 2026-06-14 Visual Capture / Voice Loop / Chinese UI Round

- GitHub reminder: push only intentional source changes to `https://github.com/KecenLi/astralive` on `main`; do not commit `.env`, `data/`, packaged `dist/`, local model weights, logs, or tokens.
- Root cause handled: camera/screen preview could be active while the auto-upload loop never restarted after `streamRef` changed; panels now track a real `streamActive` state, and capture scheduling is source-level so camera and screen can run independently.
- Voice loop handled: TEN VAD now creates the trace before the first streamed chunk, the final metadata reports actual streamed chunks/bytes, ASR worker pipe/process crashes retry once, and ASR/TTS local GPU work is serialized to avoid same-GPU memory races.
- Visual failure handling: if Vertex returns timeout/429, the UI now says the frame was uploaded but cloud vision failed, instead of implying camera/screen permission failure.
- Extreme-noise guard: if local ASR returns only punctuation/no language content, MODVII now logs and returns to listening instead of sending meaningless text to the LLM.
- Desktop pet toggle: hiding the transparent always-on-top pet now closes and recreates the pet window instead of relying on `BrowserWindow.hide()` visibility state.
- Local ASR default for deadline speed: `.env` is ignored and currently uses `LOCAL_ASR_MODEL=base`, `LOCAL_ASR_MODEL_PATH=D:\assist ai\models\whisper\base.pt`, `LOCAL_ASR_DEVICE=cuda`; `large-v3.pt` remains available but is not the default.
- Validation before packaging: backend pytest `92 passed`, `ruff check app` clean, web TypeScript build check clean, Vitest `53 passed`, verifier script syntax check clean.
- Source dev blind soak against the real local backend: 3/3 rounds returned to listening, 0 hard timeouts, 0 server error events, visual answered 2/2 expected visual rounds, with `vision.summary` observed.
- Final packaged mock smoke: passed for main render, Live2D, text dialogue, prompt-attack refusal, screen capture, screen+voice concurrency, desktop pet toggle/click, and backend audio websocket.
- Final packaged real-provider smoke: `low_noise` passed with local Whisper + Vertex vision/LLM + CosyVoice3, auto-returned to listening, visual summary updated, no server errors. `white_noise` did not crash but base Whisper produced punctuation-only text, now guarded.
- Latest portable exe: `D:\assist ai\dist\desktop\MODVII 0.1.0.exe`, timestamp `2026-06-14 20:38:40 +0800`, SHA256 `94CE60E914D52065AE696F6466276EFD0822CCA5766F83DAEFA46D7C444B76A0`.
- Latest installer: `D:\assist ai\dist\desktop\MODVII Setup 0.1.0.exe`, timestamp `2026-06-14 20:38:38 +0800`, SHA256 `D6FF62F6D8CA48D861D4B32CE56714C33E7B9A8B4CC0920083BC22A9175BEFA5`.

## 2026-06-14 Visual Capture Contention / Continuous Listening Round

- GitHub reminder: push only intentional source changes to `https://github.com/KecenLi/astralive` on `main`; do not commit `.env`, `data/`, `.cache`, packaged `dist/`, local model weights, logs, or tokens.
- Live-log finding from the user-running portable: microphone TEN VAD did trigger and sent audio, but Vertex vision returned `HTTP 429 RESOURCE_EXHAUSTED` at 21:01:41 and 21:01:51 while camera/screen capture was active.
- Root cause handled: camera and screen may remain enabled together, but renderer-side frame encoding is now serialized so two visual sources cannot simultaneously block the Electron renderer thread that also runs VAD callbacks.
- Capture CPU contention fix: frame JPEG encoding now uses async `canvas.toBlob()` instead of synchronous `canvas.toDataURL()`, reducing main-thread stalls while microphone VAD is armed.
- Voice-priority fix: app statuses `listening`, `thinking`, and `speaking` now use idle visual cadence instead of active cadence; manual focus captures still work.
- Continuous listening fix: if Electron lacks native `SpeechRecognition`, the keyword-listen fallback no longer runs TEN VAD only once. On no-speech timeout it automatically restarts while conversation mode is enabled.
- Rearm race fix: keyword recognition restart no longer trusts stale React `recognitionActive` state, clears old recognition/VAD instances before restart, and retries if the browser reports recognition is already starting.
- Validation before push this round: `npm --prefix apps/web test -- --run` passed with 53 tests; `npm --prefix apps/web run build` passed.
- Latest portable for this round, built without overwriting the currently running old portable: `D:\assist ai\dist\desktop\MODVII-0.1.0-listeningfix-20260614-2112.exe`, timestamp `2026-06-14 21:10:30 +0800`, SHA256 `B9C1FD65CF69F6C97F8A303A373C1ACF8DA9F376517256F2FC28B035096038B1`.
- Packaging note: the currently running `D:\assist ai\dist\desktop\MODVII 0.1.0.exe` is still the old packaged build. Use the `listeningfix` portable above for this round, or close MODVII and rebuild the canonical filename later.

## 2026-06-14 Visual Timeout / Manual Capture Round

- Current live-log root cause: the old running portable still uses `VISION_REQUEST_TIMEOUT_SECONDS=5`, so Vertex visual calls time out with blank `TimeoutError`; uncancelled background requests then produced HTTP 429 `RESOURCE_EXHAUSTED`.
- Fix: default visual and Vertex request timeout raised to 20s, timeout details are explicit, `vision.error` is emitted for visible failures, and manual/focus captures bypass ordinary visual cooldown and client scene-hash dedupe.
- Local `.env` was updated to `VISION_REQUEST_TIMEOUT_SECONDS=20` and `VERTEX_AI_REQUEST_TIMEOUT_SECONDS=20`; `.env` remains ignored and must not be committed.
- Latest portable while the old exe is still locked: `D:\assist ai\dist\desktop\MODVII-0.1.0-visionfix-20260614-1742.exe`, SHA256 `E79460AFFFD3A003EABD2DB47AB9FE053840A4BFCFC17B4162C821B70859DADC`.
- Latest unpacked exe: `D:\assist ai\dist\desktop\win-unpacked\MODVII.exe`, SHA256 `1FA93C3471C11DC8128998C662C705104E4528B98901B61C8A25216ACDA424C5`.
- Latest installer: `D:\assist ai\dist\desktop\MODVII Setup 0.1.0.exe`, SHA256 `14AC05C97A32308D058088E747349962077BAE2759047243AEA6B10DCAF444BC`.
- Warning: `D:\assist ai\dist\desktop\MODVII 0.1.0.exe` is still the old locked portable from 17:17 and should not be treated as latest until it is rebuilt after closing the app.
- Validation before push this round: backend pytest/ruff, web vitest/build, local whisper worker py_compile, server exe health smoke. Desktop renderer smoke was skipped because it kills the user’s currently running MODVII process.

## 2026-06-14 Local Whisper large-v3 / CUDA Round

- Claude verified `LOCAL_ASR_MODEL=large-v3` on `LOCAL_ASR_DEVICE=cuda` with Chinese initial prompt and beam search; Agent 0 integrated the missing packaged-runtime path support.
- `LOCAL_ASR_MODEL_PATH` is now honored by the backend and passed to `scripts/local_whisper_worker.py` as an explicit model file. This avoids bundling the 3GB `large-v3.pt` into Git or the portable exe.
- Current local `.env` points to `D:\assist ai\models\whisper\large-v3.pt`; `.env` remains ignored and must not be committed. `C:\Users\YHT\.cache\whisper` is now only a junction to the D-drive model folder for compatibility with older scripts.
- Packaged behavior: Electron ships the worker script, while Whisper weights stay in the user cache or a configured model path. If the file is absent, the verifier and worker fail with a clear missing-model message instead of silently falling back.
- Latest portable for this round: `D:\assist ai\dist\desktop\MODVII-0.1.0-asr-largev3-20260614-1754.exe`, SHA256 `DAA0E3B66A136361048CC38694319C908DC5BB4CF72A29C7B74719CDF4744E42`.
- Latest packaged server exe SHA256: `92423D1E2ADDD911780E91A7F7A996316B951BBB2E6860ED2FE05D692E28AFB5`.
- Validation before push this round: backend pytest/ruff, web vitest/build, local ASR large-v3 verifier, local whisper worker py_compile, server exe health smoke.

## 2026-06-14 C Drive Cache Migration Round

- Stopped stale MODVII, dev server, local ASR/TTS worker, and Electron builder processes before moving files.
- Moved local Whisper checkpoints to `D:\assist ai\models\whisper` and updated ignored `.env` to `LOCAL_ASR_MODEL_PATH=D:\assist ai\models\whisper\large-v3.pt`.
- Created a junction from `C:\Users\YHT\.cache\whisper` to `D:\assist ai\models\whisper`, so older commands that still use the default Whisper cache path do not redownload to C.
- Set user-level cache roots to D drive: `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE`, `MODELSCOPE_CACHE`, `TORCH_HOME`, `npm_config_cache`, `ELECTRON_CACHE`, and `ELECTRON_BUILDER_CACHE`.
- Removed old project-related C-drive caches and temp directories: pip/npm/electron/electron-builder caches plus MODVII portable `3F*` and `modvii-*` temp folders.
