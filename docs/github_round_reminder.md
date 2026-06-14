# GitHub Round Reminder

## Current Repository

- Local project root: `D:\assist ai`
- Remote: `origin` -> `https://github.com/KecenLi/astralive.git`
- Target branch: `main`
- Local docs note: `.gitignore` ignores `README.md` and `docs/` for private/local records, but `docs/github_round_reminder.md` is already tracked. Check `git ls-files` and `git status -sb` before assuming a Markdown change will be pushed.
- Do not force-add ignored local records, API logs, Live2D assets, installers, `.env`, ADC files, or tokens unless the user explicitly asks for that exact publication.

每轮工作结束前，Agent 需要执行：

1. 检查 `git status -sb`，确认没有意外文件或敏感配置进入待提交范围。
2. 对本轮改动运行相关测试或说明未运行原因。
3. 如果用户要求推送，提交清晰 commit，并推送到 GitHub。
4. 最终回复中写明分支、commit、push 状态和验证结果。

注意：不要提交 `.env`、令牌、ADC 文件、构建缓存或本地日志。

## Multi-Agent Rule

- Agent 0 owns coordination, integration, final verification, commit, and push.
- If a round has multiple independent tracks, Agent 0 should proactively delegate bounded side work to subagents, especially GitHub/source research, UI-only work, test triage, packaging smoke checks, or documentation updates.
- Delegated work must have explicit file ownership or a read-only question. Subagents must not revert user changes or main-agent changes, and their results must be reviewed before integration.
- Every round that uses subagents should record which agent did what, what files changed, and any residual risk before pushing.

## Subagent Usage Rules

- Use subagents only for bounded work that can be reviewed independently: source research, GitHub issue/PR inspection, UI-only passes, test log triage, packaging smoke checks, or documentation updates.
- Do not delegate final integration ownership, secret handling, commit creation, push decisions, or broad refactors that can conflict with another active worker.
- Every delegation must state the objective, allowed files or read-only scope, expected output, validation command if any, and the rule to not revert user or other-worker changes.
- The main worker must review subagent output before using it, reconcile conflicts, and document any files changed by subagents in the round notes.
- If no subagent is used, no extra record is needed beyond final response; if a subagent is used, record name/scope/result before pushing.

## Push Checklist

- Run `git status -sb` and inspect `git diff --stat`.
- Run relevant checks for touched areas; for documentation-only rounds, spell out that no code tests were needed.
- Run `scripts\guard-public-tree.ps1` before publishing any round that touched assets, secrets, docs, installers, or config.
- Push only after tests pass or after documenting a deliberate skip approved by the user.
- Final response must say branch, commit, push state, changed files, and verification result.

## 2026-06-14 Round Notes

- Repository remote: `https://github.com/KecenLi/astralive.git`
- Branch target: `main`
- This round must be pushed after tests pass.
- Voice/turn-taking references checked this round:
  - TEN-framework/ten-vad: frame-level real-time VAD; tuned locally with lower threshold, lower RMS floor, longer end debounce, and pre-roll.
  - ricky0123/vad / vad-web: browser-side speech segment callbacks and ONNX/Silero fallback remain in MODVII.
  - LiveKit Agents turn detector: use VAD plus explicit turn state and response gating; MODVII now gates camera/screen upload while response is in progress.
  - pipecat-ai/smart-turn: semantic/audio turn detection works best with full-turn audio context; MODVII keeps full PCM turn buffers for fallback ASR instead of only last segment.
- Do not copy upstream source code verbatim. Keep source/license references in docs and implement MODVII-specific state handling.

## 2026-06-14 Follow-up Notes

- Root cause fixed this round: screen/camera vision frames were awaited inside the session WebSocket event loop, so a slow vision call could block microphone chunks. Visual analysis now runs as a cancellable background task and voice/text/interrupt events take priority.
- Current network observation: Hong Kong VPN is better for Gemini API-style endpoints, but Vertex Live in `us-central1` still carries long-haul latency and should not be treated as solved by VPN alone.
- China provider route added but not activated: use `scripts/configure-china-provider.ps1` after the user provides paid API keys. Default route is DashScope Hong Kong `qwen-plus` for LLM/Vision plus optional SiliconFlow ASR/TTS; Beijing route keeps `qwen3.5-plus`.
- Live2D mouth fix: Haru uses `PARAM_MOUTH_OPEN_Y`; controller now writes common Cubism mouth parameter aliases and maps MODVII response text to available Haru motion groups.
- Validation before push: backend pytest and ruff, web eslint/tsc/vitest/build.

## 2026-06-14 Visual Scheduler Notes

- Visual frame handling is now a bounded scheduler, not a single blocking task: active tasks are capped by `VISION_MAX_CONCURRENCY`, pending frames by `VISION_PENDING_FRAME_LIMIT`, and stale results by `VISION_RESULT_MAX_AGE_SECONDS`.
- Latest-frame-wins is applied per source (`screen`, `camera`, `focus`, `general`), so screen and camera can run in parallel while repeated screen frames replace older pending screen frames.
- `VisionService.analyze_frame(..., commit=False)` allows the scheduler to discard stale provider results before they update `session.last_visual_summary` or the UI.
- Domestic provider script now includes DashScope, SiliconFlow, Volcano Ark, Baidu AI Studio/Qianfan, DeepSeek, Kimi, Zhipu, Tencent Hunyuan, and MiniMax routes. DeepSeek is text-only in the route template; use a vision-capable provider for screen/camera.

## 2026-06-14 Lisette Local Reference Notes

- Lisette source checked: ShiraLive2D sample page and BOOTH listing state the model is free but non-commercial only. Treat it as local personal reference, not a public/commercial package asset.
- Do not commit `apps/web/public/live2d/lisette/` or `.installers/lisette-drive/lisette_v2.zip`; both are ignored and blocked by the public-tree guard.
- Install with `scripts/install-lisette-live2d.ps1 -AcceptNonCommercialTerms -SetEnv` after `lisette_v2.zip` is available locally.
- The installer patches `Lisette.model3.json` with Pixi-compatible expression/motion groups and `ParamMouthOpenY` lip sync.
- Live2D rendering now uses non-premultiplied alpha plus high-DPI Pixi settings so Lisette stays clear in transparent desktop-pet windows.
- This round must push only code/scripts/config notes, not the Lisette asset files.

## 2026-06-14 Voice Latency / UI Round Notes

- Current desktop log finding: microphone VAD did send final audio, but Gemini Live timed out waiting for streaming response and the Vertex fallback then hit HTTP 429 / resource exhausted. The fix must make provider failure fast and visible instead of leaving the app silent.
- This round uses subagent `Noether` for UI/desktop-pet-only work. Agent 0 keeps ownership of MicPanel state, backend visual cooldown, tests, packaging, commit, and push.
- GitHub comparison sources checked this round include Open-LLM-VTuber, RealtimeSTT, Silero VAD, openWakeWord, LLM-Live2D-Desktop-Assitant, and waifu-companion. MODVII should follow their proven effort level: local wake/VAD gating, provider fallback/cooldown, transparent pet mode, clickable avatar interactions, model/expression mapping, and explicit fallback states.

## 2026-06-14 Real Noise / ASR-First Round Notes

- The desktop interaction verifier now uses a continuous noise bed: silence regions are low-level deterministic noise, not zeroes. Current verified noise fixture: `file-noise-bed`, level `0.012`, lead `0.8s`, tail `2.8s`.
- Real API smoke before ASR fix failed because `ASR_PROVIDER=vertex_ai` routed 16k PCM into Gemini Live ASR and timed out. MODVII now defaults PCM ASR to batch transcription: PCM -> WAV -> Vertex/Gemini `generateContent`; Live ASR is only explicit `metadata.asr_mode=live`.
- Real API smoke after ASR fix passed with Vertex ASR/LLM, concurrent screen frames, and CosyVoice3 TTS. Observed latency was still high: ASR final about `16.1s`, text final about `19.2s`, audio done about `76.1s`.
- CosyVoice3 now has a persistent worker (`scripts/cosyvoice3_worker.py`) so repeated local TTS calls reuse the loaded model. First call can still be slow; subsequent calls should be measured separately before judging local TTS viability.
- External voice pipeline references checked: RealtimeSTT (`https://github.com/KoljaB/RealtimeSTT`), FunASR (`https://github.com/modelscope/FunASR`), SenseVoice (`https://github.com/FunAudioLLM/SenseVoice`), sherpa-onnx (`https://github.com/k2-fsa/sherpa-onnx`), Open-LLM-VTuber (`https://github.com/Open-LLM-VTuber/Open-LLM-VTuber`). Practical conclusion: keep MODVII provider-swappable, prefer local or near-region ASR for wake/VAD final turns, and avoid Gemini Live as the only speech endpoint.

## 2026-06-14 Local ASR / Packaged CosyVoice3 Round Notes

- Local config switched to `ASR_PROVIDER=local_whisper`, `REALTIME_PROVIDER=none`, `TTS_PROVIDER=cosyvoice3`. `.env` stays local and must not be committed.
- Packaged TTS root cause fixed: Electron now ships `resources/scripts/cosyvoice3_worker.py`, `cosyvoice3_synth.py`, and `local_whisper_worker.py`; server providers resolve scripts from packaged resources before failing.
- Local ASR worker added with `openai-whisper` plus `imageio-ffmpeg` fallback. Current smoke on `data\cache\modvii-test-speech.wav`: `local_whisper` base model returned text in about `2.7-2.9s` standalone; in two-round WebSocket soak, ASR final after audio-final was about `0.40-0.57s` after prewarm.
- CosyVoice3 voice is fixed through `COSYVOICE3_SEED=7327`; provider sends the seed to both one-shot and worker scripts.
- Server fixed realtime failure notices now use the configured TTS provider instead of silent text-only notices when `TTS_PROVIDER` is not `mock`.
- Audio provider prewarm is enabled by `AUDIO_PREWARM_ENABLED=true`; WebSocket session ready starts local ASR/TTS workers in the background without playing any prompt.
- Current local TTS limitation is CPU inference speed, not missing script or API latency. Two-round local soak passed with no errors, but CosyVoice3 audio done after audio-final still took about `38-45s` hot on this machine. For fast spoken replies, next round should either move CosyVoice3 to GPU if available or add a faster local TTS route while keeping CosyVoice3 as high-quality mode.
- Validation before push this round: backend pytest/ruff/py_compile, `verify-local-asr.ps1`, `verify-local-tts.ps1`, `verify-real-realtime-soak.ps1` with local providers, `scripts/package.ps1 -SkipLive2D`, and packaged `verify-desktop-interaction.mjs`.

## 2026-06-14 Streaming / Cost / Provider Lifecycle Round Notes

- This round must be pushed after validation. Commit only source, tests, env example, and tracked docs; do not commit `.env`, `data/`, `.installers/`, packaged `dist/`, Live2D local assets, or API logs.
- Subagents used:
  - Halley: frontend scene-hash threshold, CostPanel token display, and `assistant.audio.done` response-turn gate.
  - Curie: LLM streaming provider work and DialogueService streaming/parser draft. Agent 0 reviewed and completed missing parser/integration.
  - Dirac: provider container, app lifespan, per-session realtime provider isolation, and realtime timeout provider tests.
  - Kepler: cost estimator, raw usage helpers, and cost tests. Agent 0 reviewed and connected service-level accounting.
- Agent 0 owns final integration: `websocket.py` streaming LLM -> sentence TTS queue, one `assistant.audio.done`, provider container usage, ASR/TTS/Vision cost recording, WebSocket realtime timeout split, frontend visual threshold store wiring, tests, package smoke, commit, and push.
- Important risk handled: frontend audio idle cannot finish a response turn while sentence TTS is between chunks. `assistant.audio.chunk` and `assistant.text.final(audio_expected=true)` both open the turn gate; only `assistant.audio.done` plus idle playback can close it.
- Important risk handled: realtime providers are not app-level shared. ASR/TTS/LLM/Vision providers are shared through `ProviderContainer`; realtime providers remain per WebSocket session and are closed on disconnect.
- Cost note: built-in Gemini 2.5 Flash prices are fallback display estimates only. Override with `COST_PRICE_TABLE_JSON` when using a paid provider route that needs accurate dollar display.
- Validation before push this round: backend `ruff check app`, backend `pytest`, web `tsc -b`, web `vitest run`, package smoke, desktop interaction smoke, and public-tree guard.

## 2026-06-14 Cancelled Audio / GPU TTS Round Notes

- User-reported freeze root cause: sentence-level TTS opened the frontend response-audio gate, but `_run_dialogue_response` did not send `assistant.audio.done` when a slow TTS task was cancelled by a new utterance. Agent 0 fixed the backend cancel/error path and added a frontend watchdog fallback.
- New regression: cancelling a dialogue response while TTS is sleeping must emit one `assistant.audio.done` with `cancelled: true`, then return session state to `listening`.
- Local CosyVoice3 route: upgraded ignored local venv to CUDA 12.8 PyTorch and set ignored local `.env` to `COSYVOICE3_DEVICE=cuda`. Do not commit `.env` or the venv.
- CosyVoice3 worker/synth now patch prompt WAV loading through `soundfile` and write PCM16 WAV directly, avoiding torchcodec/FFmpeg DLL failures with newer torchaudio on Windows.
- Observed local TTS timing after fix: single verification call succeeded; same-provider two-call smoke showed cold first call about `19.2s` and hot second call about `2.23s` on this machine. Treat cold prewarm as important before demos.
- Public tree guard now explicitly allows only the two already tracked safe docs: `docs/cosyvoice3_setup.md` and `docs/github_round_reminder.md`; all other ignored docs remain blocked from accidental publication.
- Subagents used this round: none. Agent 0 owned backend/frontend/CosyVoice script changes, validation, commit, and push.
- Validation before push this round: backend `ruff check app`, backend `pytest`, web `tsc -b`, web `vitest run`, local CosyVoice3 TTS, package smoke, desktop interaction smoke, and public-tree guard.
