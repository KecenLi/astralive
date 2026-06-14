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

const modeLabel: Record<string, string> = {
  sleep: "睡眠",
  low_cost: "省流",
  active: "活跃",
  focus: "高清",
};

const statusLabel: Record<string, string> = {
  sleeping: "睡眠",
  awake: "已唤醒",
  listening: "监听",
  thinking: "思考",
  speaking: "说话",
  interrupted: "已打断",
};

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
        <span>成本</span>
      </div>
      <div className={`cost-mode mode-${cost.mode}`}>
        <span>{modeLabel[cost.mode] ?? cost.mode}</span>
        <small>{statusLabel[status] ?? status}</small>
      </div>
      <div className="savings-story" aria-label="成本可视化">
        <strong>
          候选帧 {formatCount(narrative.candidateFrames)} -&gt; 实际视觉调用{" "}
          {formatCount(narrative.actualVisionCalls)}
        </strong>
        <span>
          节省视觉调用 {formatCount(narrative.savedVisionCalls)} / 缓存命中{" "}
          {formatCount(cost.scene_cache_hits)}
        </span>
        <span>
          估算节省 {formatUsd(cost.estimated_visual_cost_saved_usd)} / 估算支出{" "}
          {formatUsd(narrative.estimatedTotalCost)} / 总调用 {formatCount(narrative.totalCalls)}
        </span>
      </div>
      <dl className="metric-grid">
        <div>
          <dt>候选帧</dt>
          <dd>{formatCount(narrative.candidateFrames)}</dd>
        </div>
        <div>
          <dt>实际调用</dt>
          <dd>{formatCount(cost.vision_calls)}</dd>
        </div>
        <div>
          <dt>缓存命中</dt>
          <dd>{formatCount(cost.scene_cache_hits)}</dd>
        </div>
        <div>
          <dt>节省调用</dt>
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
          <dt>本地去重</dt>
          <dd>{formatCount(cost.client_deduped_frames)}</dd>
        </div>
        <div>
          <dt>睡眠拦截</dt>
          <dd>{formatCount(cost.sleep_blocked_frames)}</dd>
        </div>
        <div>
          <dt>语音延迟发送</dt>
          <dd>{formatCount(cost.voice_priority_deferred_frames)}</dd>
        </div>
        <div>
          <dt>冷却丢帧</dt>
          <dd>{formatCount(cost.visual_cooldown_drops)}</dd>
        </div>
        <div>
          <dt>排队丢帧</dt>
          <dd>{formatCount(cost.visual_pending_drops)}</dd>
        </div>
        <div>
          <dt>过期丢弃</dt>
          <dd>{formatCount(cost.stale_visual_results_discarded)}</dd>
        </div>
        <div>
          <dt>低置信/高清</dt>
          <dd>
            {formatCount(cost.visual_confidence_low_count)} / {formatCount(cost.focus_requests)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
