# MODVII Visibility Scoring Plan

Date: 2026-06-14

Status: planning and source-registration pass. This document defines the work split for Agent 0, Halley, and Dirac. It does not imply that external source code, prompts, assets, or dependencies have been copied into MODVII.

## Goal

Make MODVII's existing hidden strengths visible during judging:

- Cost control must show what was avoided, not only what was spent.
- Vision must show uncertainty and request better input instead of hallucinating.
- Conversation memory must be demonstrable in the UI and demo script.
- Bounding boxes must be validated before becoming a main demo feature.

## Reference Discipline

Use these projects as public references for concepts, data organization, and API conventions only. MODVII implementation remains local and original.

| Reference | License note | What MODVII may reference | What MODVII must not do |
| --- | --- | --- | --- |
| LiteLLM, <https://github.com/BerriAI/LiteLLM> | MIT for non-enterprise repository portions; enterprise directory has separate terms | Pricing table shape, cost-per-call concept, usage tokens multiplied by provider/model prices | Do not copy source, config, or enterprise logic |
| OpenLLMetry, <https://github.com/traceloop/openllmetry> | Apache-2.0 | Observability metric dimensions: latency, token count, cost, cache hit, provider/status tags | Do not add OpenTelemetry dependency in this round; do not copy instrumentation code |
| Gemini cookbook, <https://github.com/google-gemini/cookbook> | Apache-2.0 | Gemini bbox prompt pattern and normalized 0-1000 coordinate convention | Do not copy notebook/code cells; write MODVII's own prompt and parser |
| Pipecat, <https://github.com/pipecat-ai/pipecat> | BSD-2-Clause | Future voice turn/interruption state-machine reference, especially sentence aggregation and smart turn behavior | No code copy this round; not part of the four visibility tasks unless Agent 0 explicitly opens a voice pass |

## Workstreams

### P0: Cost Narrative / Savings Panel

Expose the delta between naive upload/call behavior and MODVII's actual behavior.

Backend metrics:

- `frame_candidates`: every camera/screen frame considered by the app.
- `frames_uploaded`: frames that reached the backend.
- `client_deduped_frames`: frames skipped by client scene-hash threshold.
- `sleep_blocked_frames`: frames blocked because MODVII was sleeping or not allowed to upload.
- `scene_cache_hits`: backend visual cache hits.
- `vision_calls_saved`: estimated vision calls avoided by cache/dedup/sleep/cooldown/pending-drop handling.
- `stale_visual_results_discarded`: provider results ignored because newer visual context already existed. This is a quality/concurrency metric, not a saved-call metric, because the provider call already happened.
- `voice_priority_deferred_frames`: frames dropped/deferred because voice response had priority.
- `visual_cooldown_drops`: frames skipped while visual provider was cooling down.
- `estimated_visual_cost_saved_usd`: display estimate using the same cost table style as existing usage estimates.

Reference guidance:

- Use LiteLLM as a sanity check for a provider/model price table shape: model key, input price, output price, and cost-per-call calculation from usage metadata.
- Use OpenLLMetry only for naming and grouping observability dimensions: per-call latency, provider, model, cache status, tokens, cost, and error status.
- Keep all visible values labeled as estimates unless they come directly from provider billing metadata.

UI narrative:

- Replace static policy bullets with live counters.
- Display: "Candidate frames N -> actual vision calls M -> saved K".
- Keep `estimated_cost_usd` clearly labeled as spend estimate and saved amount as estimate.
- Include one compact "端云协同" story line:
  - "本可上传 N 帧，实际视觉调用 M 次，缓存/睡眠/去重/限流节省 K 次，估算省 $X。"

Demo expectation:

- Start screen/camera capture for two minutes with idle and active states.
- Show candidate frames rising faster than actual vision calls.
- Point to cache hits and saved call counters while the visual summary remains stable.
- Screenshot the panel for the competition document.

### P0: Vision Self-Check / Focus Request

Connect low-confidence visual results to an explicit clarification loop.

Provider contract:

- Extend `VisionResult` with `need_focus: bool`, `focus_reason: str | None`.
- Providers should parse structured JSON when available:
  - `summary`
  - `confidence`
  - `need_focus`
  - `focus_reason`
  - `ocr_text`
  - `objects`
- If parsing fails, keep existing summary fallback.

Reference guidance:

- Use Gemini cookbook only to shape the model request style for structured visual output. Do not copy notebook code.
- Self-check should not depend only on provider `confidence` because some providers currently synthesize fixed confidence values. Prefer combined signals: structured `need_focus`, low confidence, short/empty OCR, "unclear" language, or invalid JSON fallback.

Runtime behavior:

- If `need_focus` is true or confidence is low, emit `vision.need_focus` with reason, confidence, and frame id.
- UI records the focus request visibly in the conversation panel and last frame status.
- Do not force a new upload without user/device permission; request focus through existing focus buttons / focus mode.

Demo expectation:

- Use a deliberately blurred or distant text image.
- Expected MODVII behavior: it refuses to overclaim, says it cannot see clearly enough, and requests focus/high-resolution capture.
- After focus mode, expected behavior is either improved answer or a clearly stated remaining uncertainty.

### P1: Conversation Memory Visibility

Backend history already exists. Make it visible and demonstrable without leaking message bodies in session state.

UI:

- Show `history_turns` in Debug or Conversation header.
- Keep history body private; only count/active memory indicator is needed.

Demo:

- Add a script section:
  1. "小七，这是我的蓝色水杯。"
  2. "它是什么颜色？"
  3. "刚才我让你记住的东西是什么？"
- Expected result: MODVII answers from conversation history, not from a new vision call.
- Capture one screenshot where `history_turns` increments and the answer resolves "它" from prior context.

### P1/P2: Bounding Box Validation Before Overlay

Do not ship bbox overlay as a judging-critical feature until provider stability is measured.

Reference guidance:

- Use Gemini cookbook's spatial understanding convention: normalized `[y_min, x_min, y_max, x_max]` coordinates in the 0-1000 range.
- Provider prompt must demand strict JSON. Parser must reject boxes outside bounds, inverted boxes, or missing labels.
- Overlay is gated by validation metrics. No bbox overlay in the main demo unless the fixed-image test is stable.

Validation script:

- Send a fixed image to the configured vision provider.
- Request object boxes as JSON with Gemini-compatible normalized coordinates `[y_min, x_min, y_max, x_max]` in the 0-1000 coordinate space.
- Run multiple attempts and report:
  - JSON parse success rate.
  - Object label consistency.
  - Coordinate bounds validity.
  - Whether boxes are stable enough for overlay.

Implementation after validation:

- Extend `VisionObject` with optional `bbox`.
- Frontend draws boxes only when coordinates are present and valid.
- If validation is weak, keep objects as text chips and skip overlay in the main demo.

Demo expectation:

- Validation pass: show image preview with 1-3 boxes and labels, plus a small "bbox validated" status.
- Validation fail: show a transparent report instead of hiding failure, e.g. "JSON parse 6/10, coordinate valid 5/10; overlay disabled for judging demo."

## Subagent Arrangement

### Agent 0

Owns:

- Overall integration.
- `CostMeter`, `SessionState`, `VisionService`, `websocket.py`, and final event payload shape.
- Final tests, packaging smoke, commit, push.
- Final demo script sanity check and screenshot checklist.

Rules:

- Do not delegate final protocol integration.
- Do not allow parallel workers to edit `websocket.py`.
- Review all subagent patches before commit.
- If speech behavior is touched later, use Pipecat as state-machine reference only after the four visibility tasks are stable.

### Halley: Frontend Visibility

Allowed files:

- `apps/web/src/components/CostPanel/CostPanel.tsx`
- `apps/web/src/components/ConversationPanel/ConversationPanel.tsx`
- `apps/web/src/lib/events.ts`
- `apps/web/src/app/store.ts`
- `apps/web/src/styles/global.css`
- frontend tests for the changed components/types

Deliverable:

- Live savings narrative in CostPanel.
- Memory turn count visible.
- Focus/self-check notices readable in ConversationPanel or status text.
- Optional bbox overlay rendering only after Dirac's validation script proves stable boxes.
- Visual treatment should make savings and self-check obvious in screenshots without turning the app into a debug dashboard.

### Dirac: Vision Structured Output and BBox Validation

Allowed files:

- `apps/server/app/contracts/model_io.py`
- `apps/server/app/providers/vision/*`
- backend tests specific to vision parsing
- `scripts/verify-vision-bbox.*`

Deliverable:

- `VisionResult.need_focus`, `focus_reason`, optional bbox model.
- Robust JSON parser/fallback for provider vision responses.
- BBox validation script that reports stability instead of assuming success.
- Patch notes for Agent 0 on any `websocket.py` event payload needed.
- Gemini-compatible bbox prompt written in MODVII's own wording, using the 0-1000 coordinate convention.
- Tests for invalid JSON, out-of-range bbox values, and missing confidence/need_focus fields.

### Agent 0 or Nash-equivalent: Cost Metrics Backend

Allowed files:

- `apps/server/app/core/cost_meter.py`
- `apps/server/app/services/vision_service.py`
- `apps/server/app/core/session_state.py`
- backend tests for savings metrics

Deliverable:

- Counters for candidate frames, skipped frames, cache hits, saved calls, and estimated saved visual cost.
- Provider/model price table remains locally owned but is checked against LiteLLM-style field organization.
- Cost events include enough fields for Halley to render the narrative without deriving backend policy in the frontend.

### Documentation / Demo Worker

Allowed files:

- `plans/modvii_visibility_scoring_plan.md`
- demo/verification script files if created outside ignored local docs
- no secrets, no `.env`, no generated logs

Deliverable:

- Demo sequence for cost savings, visual self-check, memory, and optional bbox validation.
- Clear pass/fail expectations and screenshots to capture.
- Source-registration entries in `docs/originality_log.md` and `docs/third_party_licenses.md`.

## Validation

- Backend unit tests for:
  - cache hits increment savings metrics;
  - voice-priority frame drops increment savings metrics;
  - low-confidence or `need_focus` vision result emits focus event;
  - structured vision JSON parser handles valid JSON and text fallback.
- Frontend unit tests for:
  - CostPanel renders saved calls and saved USD;
  - ConversationPanel renders memory count and focus notice.
- Smoke:
  - `ruff check app`
  - `pytest`
  - `tsc -b`
  - `vitest run`
  - desktop interaction smoke if UI changes are substantial.
- Demo dry-run:
  - Savings panel shows nonzero saved calls after idle/repeated frames.
  - Vision self-check asks for focus on unclear input.
  - Memory count increments and pronoun question resolves from history.
  - BBox validation reports pass/fail honestly before overlay is enabled.

## GitHub Reminder

- Update `docs/github_round_reminder.md` before push.
- Commit only source, tests, scripts, and safe planning docs.
- Do not commit `.env`, API logs, model assets, Live2D assets, `dist/`, or `data/`.
