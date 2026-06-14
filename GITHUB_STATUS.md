# MODVII GitHub Status

- Repository: https://github.com/KecenLi/astralive
- Branch: main
- Latest feature commit for this round: `e286ce6` (`Polish final desktop interaction timing`)
- To check the current latest commit: `git rev-parse --short HEAD`
- Reminder: after each implementation and test round, commit and push intentional source changes, then report the commit hash, latest packaged exe path, timestamp, and SHA256.

## 2026-06-14 Final DDL Polish Round

- GitHub reminder: push only intentional source changes to `https://github.com/KecenLi/astralive` on `main`; do not commit `.env`, `data/`, packaged `dist/`, local model weights, logs, or tokens.
- Visual summary panel: `融合 / 摄像头 / 屏幕` summary area is now taller by default and vertically resizable with the browser resize handle; it sits above chat history so expanding it pushes chat down instead of compressing text into a tiny box.
- Subtitle timing: normal ASR -> LLM -> TTS dialogue now sends each assistant text segment only after its matching TTS segment has synthesized successfully. This keeps visible subtitles aligned with voice readiness instead of showing the full answer long before audio starts.
- Claude fixes included in the same package:
  - Desktop pet avatar region is draggable, so the transparent pet can be grabbed directly.
  - Live2D built-in pointer auto-interaction is disabled, stopping the character from staring at/following the mouse and preventing the canvas from stealing pet-window drag events.
  - Idle pulse motion keeps the Live2D model alive after mouse-follow is disabled.
- Validation:
  - Backend pytest: `95 passed, 2 warnings`.
  - Backend lint: `ruff check app` clean.
  - Frontend Vitest: `54 passed`.
  - Frontend production build: passed.
  - Packaged portable smoke: passed, backend health `http://127.0.0.1:11851/health`.
  - Real-provider smoke before final repack with the same source changes: `desktop-interaction-20260614-135958.json`, errors `0`, HTTP 429 `0`, timeout `0`; text delta and first audio chunk were aligned at about `7473ms` / `7505ms`.
- Latest portable exe: `D:\assist ai\dist\desktop\MODVII 0.1.0.exe`, timestamp `2026-06-14 22:03:06 +0800`, SHA256 `EBE8456C6915D6C1168A506F3074EE35FDF87E1AFCEE013808FA584106ACC8E9`.
- Latest installer: `D:\assist ai\dist\desktop\MODVII Setup 0.1.0.exe`, timestamp `2026-06-14 22:03:04 +0800`, SHA256 `9E1FE2B3FE900A46C5FC55B565932598C1EC849ECDC2FAC9031BE4CE0F35174C`.

## 2026-06-14 Final Repackage / Real API Smoke Round

- GitHub reminder: push only intentional source changes to `https://github.com/KecenLi/astralive` on `main`; do not commit `.env`, `data/`, packaged `dist/`, local model weights, logs, or tokens.
- Source commits this round:
  - `6595d5f` Add desktop pet shortcut to restore main window.
  - `87bff77` Harden real API smoke and dialogue marker parsing.
- Packaged fix: rebuilt canonical portable and installer after the local Whisper prompt update and dialogue marker parser update.
- ASR fix: local Whisper Chinese initial prompt now includes MODVII visual terms such as `摄像头摘要`, `屏幕摘要`, `融合摘要`, and `屏幕捕捉`; direct local-ASR verification on the noisy fake mic WAV recognized `摄像头摘要` and `屏幕摘要` correctly.
- Verification fix: real API desktop smoke now refreshes its generated CosyVoice speech cache for each requested test sentence, so reports no longer reuse stale audio while claiming a new request.
- Dialogue fix: server strips both `[[emotion:thinking]]` and bare `[[thinking]]` markers before text deltas/TTS, preventing model control tags from leaking into UI or speech.
- Validation:
  - Backend targeted tests: `67 passed, 1 warning`.
  - Backend lint: `ruff check app` clean.
  - Final packaged real-provider smoke: `desktop-interaction-20260614-134601.json` passed with `local_whisper` ASR, Vertex vision/LLM, CosyVoice3 TTS, and realtime disabled.
  - Real smoke metrics: errors `0`, HTTP 429 `0`, timeouts `0`, auto-returned to listening `true`, visual summary updated `true`, marker leak `false`.
  - Real smoke final cost estimate: `$0.0029318`; visual estimated savings `$0.0074046`; vision calls `1`, LLM calls `1`, ASR calls `1`, TTS calls `4`.
- Latest portable exe: `D:\assist ai\dist\desktop\MODVII 0.1.0.exe`, timestamp `2026-06-14 21:45:37 +0800`, SHA256 `8644DD3EDD4EE6F6EB072CD2C35E47EA1D63EAE584445E60D83A3DC771468C1A`.
- Latest installer: `D:\assist ai\dist\desktop\MODVII Setup 0.1.0.exe`, timestamp `2026-06-14 21:45:36 +0800`, SHA256 `647FBD91749AE78270D9A023DFFB0A436A89199AE4279F157557782E4E71BE3D`.
- Known residual: base Whisper still produced one homophone typo in the final packaged smoke (`涉像头` vs `摄像头`), but the downstream LLM answered correctly. For maximum ASR accuracy, switch back to a larger Whisper model; for deadline speed, current default remains `base`.

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

## 2026-06-14 Split Visual Context Round

- GitHub reminder: push only intentional source changes to `https://github.com/KecenLi/astralive` on `main`; do not commit `.env`, `data/`, packaged `dist/`, local model weights, logs, or tokens.
- Backend visual state now keeps `camera_visual_summary`, `screen_visual_summary`, and `fused_visual_summary` separately. The old `last_visual_summary` remains for compatibility and stores the latest single-source raw summary.
- Vision cache is source-aware: camera scene hash/cache no longer overwrites screen scene hash/cache, and screen no longer invalidates camera cache.
- `vision.summary` and session payloads now include `visual_context` with `camera`, `screen`, `fused`, and per-source timestamps.
- Dialogue and realtime prompts now include all available visual context: camera recent view, screen recent view, and fused visual summary.
- Frontend conversation panel now displays three rows: `融合`, `摄像头`, and `屏幕`; the store keeps all three fields separately.
- Validation before push this round: backend `94 passed, 2 warnings`, `ruff check app` clean, web Vitest `54 passed`, web production build passed.
- Packaging note: not packaged yet in this round; use source/dev build until a new portable is produced.

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
