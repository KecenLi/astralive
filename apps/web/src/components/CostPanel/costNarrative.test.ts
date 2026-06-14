import { describe, expect, it } from "vitest";

import { CostMeter } from "../../lib/events";
import { buildCostNarrative } from "./CostPanel";

const baseCost: CostMeter = {
  frames_uploaded: 0,
  bytes_uploaded: 0,
  vision_calls: 0,
  llm_calls: 0,
  asr_calls: 0,
  tts_calls: 0,
  estimated_input_tokens: 0,
  estimated_output_tokens: 0,
  estimated_cost_usd: 0,
  mode: "sleep",
  last_latency_ms: null,
};

describe("buildCostNarrative", () => {
  it("uses explicit observability counters when present", () => {
    const narrative = buildCostNarrative({
      ...baseCost,
      vision_calls: 4,
      frame_candidates: 22,
      vision_calls_saved: 18,
      llm_calls: 1,
      estimated_cost_usd: 0.01,
    });

    expect(narrative.candidateFrames).toBe(22);
    expect(narrative.actualVisionCalls).toBe(4);
    expect(narrative.savedVisionCalls).toBe(18);
    expect(narrative.estimatedCostPerCall).toBeCloseTo(0.002);
  });

  it("falls back to component savings when the backend has not sent saved calls yet", () => {
    const narrative = buildCostNarrative({
      ...baseCost,
      frames_uploaded: 3,
      vision_calls: 2,
      client_deduped_frames: 5,
      sleep_blocked_frames: 8,
      scene_cache_hits: 4,
      visual_cooldown_drops: 1,
    });

    expect(narrative.candidateFrames).toBe(16);
    expect(narrative.savedVisionCalls).toBe(18);
  });
});
