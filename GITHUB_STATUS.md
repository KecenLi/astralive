# MODVII GitHub Status

- Repository: https://github.com/KecenLi/astralive
- Branch: main
- Latest feature commit for this round: this commit, local Whisper large-v3 packaging integration
- To check the current latest commit: `git rev-parse --short HEAD`
- Reminder: after each implementation and test round, commit and push intentional source changes, then report the commit hash, latest packaged exe path, timestamp, and SHA256.

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
