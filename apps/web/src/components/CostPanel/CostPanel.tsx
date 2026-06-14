import { Gauge } from "lucide-react";

import { useAppStore } from "../../app/store";

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function metricValue(value: number | null | undefined) {
  return isFiniteNumber(value) ? Math.max(0, Math.round(value)) : 0;
}

function formatCount(value: number | null | undefined) {
  return isFiniteNumber(value) ? Math.round(value).toLocaleString("en-US") : "0";
}

function formatUsd(value: number | null | undefined) {
  return isFiniteNumber(value) ? `$${value.toFixed(4)}` : "$0.0000";
}

export function buildCostNarrative(cost: ReturnType<typeof useAppStore.getState>["cost"]) {
  const actualVisionCalls = metricValue(cost.vision_calls);
  const componentSavedCalls =
    metricValue(cost.client_deduped_frames) +
    metricValue(cost.sleep_blocked_frames) +
    metricValue(cost.scene_cache_hits) +
    metricValue(cost.voice_priority_deferred_frames) +
    metricValue(cost.visual_cooldown_drops) +
    metricValue(cost.visual_pending_drops);
  const savedVisionCalls = metricValue(cost.vision_calls_saved ?? componentSavedCalls);
  const candidateFrames = metricValue(
    cost.frame_candidates ?? cost.frames_uploaded + metricValue(cost.client_deduped_frames) + metricValue(cost.sleep_blocked_frames),
  );
  const totalCalls =
    actualVisionCalls + metricValue(cost.llm_calls) + metricValue(cost.asr_calls) + metricValue(cost.tts_calls);
  // Total estimated spend is a hard, defensible number. We deliberately do not
  // surface a blended "per call" average: vision/LLM/ASR/TTS have very
  // different unit prices, so dividing total cost by total call count produces
  // a figure with no real meaning that is hard to justify to reviewers.
  const estimatedTotalCost = isFiniteNumber(cost.estimated_cost_usd) ? cost.estimated_cost_usd : 0;

  return {
    actualVisionCalls,
    candidateFrames,
    estimatedTotalCost,
    savedVisionCalls,
    totalCalls,
  };
}

export function CostPanel() {
  const cost = useAppStore((state) => state.cost);
  const status = useAppStore((state) => state.status);
  const narrative = buildCostNarrative(cost);

  return (
    <section className="panel cost-panel">
      <div className="panel-title">
        <Gauge size={18} />
        <span>Cost</span>
      </div>
      <div className={`cost-mode mode-${cost.mode}`}>
        <span>{cost.mode}</span>
        <small>{status}</small>
      </div>
      <div className="savings-story" aria-label="Cost observability">
        <strong>
          Candidate frames {formatCount(narrative.candidateFrames)} -&gt; actual vision calls{" "}
          {formatCount(narrative.actualVisionCalls)}
        </strong>
        <span>
          Saved vision calls {formatCount(narrative.savedVisionCalls)} / cache hits{" "}
          {formatCount(cost.scene_cache_hits)}
        </span>
        <span>
          Est. saved {formatUsd(cost.estimated_visual_cost_saved_usd)} / est. spend{" "}
          {formatUsd(narrative.estimatedTotalCost)} over {formatCount(narrative.totalCalls)} calls
        </span>
      </div>
      <dl className="metric-grid">
        <div>
          <dt>candidate frames</dt>
          <dd>{formatCount(narrative.candidateFrames)}</dd>
        </div>
        <div>
          <dt>actual calls</dt>
          <dd>{formatCount(cost.vision_calls)}</dd>
        </div>
        <div>
          <dt>cache hits</dt>
          <dd>{formatCount(cost.scene_cache_hits)}</dd>
        </div>
        <div>
          <dt>saved calls</dt>
          <dd>{formatCount(narrative.savedVisionCalls)}</dd>
        </div>
        <div>
          <dt>输入 tokens</dt>
          <dd>{formatCount(cost.estimated_input_tokens)}</dd>
        </div>
        <div>
          <dt>输出 tokens</dt>
          <dd>{formatCount(cost.estimated_output_tokens)}</dd>
        </div>
        <div>
          <dt>延迟</dt>
          <dd>{cost.last_latency_ms ?? 0} ms</dd>
        </div>
        <div>
          <dt>估算费用</dt>
          <dd>{formatUsd(cost.estimated_cost_usd)}</dd>
        </div>
      </dl>
      <dl className="observability-list">
        <div>
          <dt>client dedupe</dt>
          <dd>{formatCount(cost.client_deduped_frames)}</dd>
        </div>
        <div>
          <dt>sleep blocked</dt>
          <dd>{formatCount(cost.sleep_blocked_frames)}</dd>
        </div>
        <div>
          <dt>voice deferred</dt>
          <dd>{formatCount(cost.voice_priority_deferred_frames)}</dd>
        </div>
        <div>
          <dt>cooldown drops</dt>
          <dd>{formatCount(cost.visual_cooldown_drops)}</dd>
        </div>
        <div>
          <dt>pending drops</dt>
          <dd>{formatCount(cost.visual_pending_drops)}</dd>
        </div>
        <div>
          <dt>stale discarded</dt>
          <dd>{formatCount(cost.stale_visual_results_discarded)}</dd>
        </div>
        <div>
          <dt>low confidence / focus</dt>
          <dd>
            {formatCount(cost.visual_confidence_low_count)} / {formatCount(cost.focus_requests)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
