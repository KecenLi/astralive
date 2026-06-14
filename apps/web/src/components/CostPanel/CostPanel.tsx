import { Gauge } from "lucide-react";

import { useAppStore } from "../../app/store";

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatCount(value: number | null | undefined) {
  return isFiniteNumber(value) ? Math.round(value).toLocaleString("en-US") : "0";
}

function formatUsd(value: number | null | undefined) {
  return isFiniteNumber(value) ? `$${value.toFixed(4)}` : "$0.0000";
}

export function CostPanel() {
  const cost = useAppStore((state) => state.cost);
  const status = useAppStore((state) => state.status);

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
      <dl className="metric-grid">
        <div>
          <dt>上传帧</dt>
          <dd>{cost.frames_uploaded}</dd>
        </div>
        <div>
          <dt>上传字节</dt>
          <dd>{cost.bytes_uploaded}</dd>
        </div>
        <div>
          <dt>视觉调用</dt>
          <dd>{cost.vision_calls}</dd>
        </div>
        <div>
          <dt>对话调用</dt>
          <dd>{cost.llm_calls}</dd>
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
      <ul className="policy-list">
        <li>未唤醒零上传</li>
        <li>画面未变化复用视觉摘要</li>
        <li>需要细节时才高清上传</li>
      </ul>
    </section>
  );
}
