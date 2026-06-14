# MODVII GitHub Status

- Repository: https://github.com/KecenLi/astralive
- Branch: main
- Latest feature commit for this round: this commit, visual timeout/manual capture fix
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
