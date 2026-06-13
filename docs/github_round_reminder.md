# GitHub Round Reminder

每轮工作结束前，Agent 需要执行：

1. 检查 `git status -sb`，确认没有意外文件或敏感配置进入待提交范围。
2. 对本轮改动运行相关测试或说明未运行原因。
3. 如果用户要求推送，提交清晰 commit，并推送到 GitHub。
4. 最终回复中写明分支、commit、push 状态和验证结果。

注意：不要提交 `.env`、令牌、ADC 文件、构建缓存或本地日志。

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
