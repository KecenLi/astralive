import { Gauge } from "lucide-react";

import { useAppStore } from "../../app/store";

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
          <dt>延迟</dt>
          <dd>{cost.last_latency_ms ?? 0} ms</dd>
        </div>
        <div>
          <dt>估算费用</dt>
          <dd>${cost.estimated_cost_usd?.toFixed(4) ?? "0.0000"}</dd>
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

