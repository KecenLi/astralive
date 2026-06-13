# GitHub Round Reminder

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
