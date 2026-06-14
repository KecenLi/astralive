import { Bug, PlugZap } from "lucide-react";

import { useAppStore } from "../../app/store";
import { createEvent } from "../../lib/events";
import { wsClient } from "../../lib/wsClient";

export function DebugPanel() {
  const connection = useAppStore((state) => state.connection);
  const sessionId = useAppStore((state) => state.sessionId);
  const audio = useAppStore((state) => state.audioCapabilities);

  return (
    <section className="panel debug-panel">
      <div className="panel-title">
        <Bug size={18} />
        <span>调试</span>
      </div>
      <dl className="metric-list">
        <div>
          <dt>连接</dt>
          <dd>{connection}</dd>
        </div>
        <div>
          <dt>会话</dt>
          <dd>{sessionId || "等待中"}</dd>
        </div>
        <div>
          <dt>实时通道</dt>
          <dd>{audio?.realtime_provider ?? "等待中"}</dd>
        </div>
        <div>
          <dt>ASR/TTS</dt>
          <dd>{audio ? `${audio.asr_provider}/${audio.tts_provider}` : "等待中"}</dd>
        </div>
        <div>
          <dt>音频</dt>
          <dd>{audio ? `${audio.input_sample_rate}->${audio.output_sample_rate} Hz / ${audio.channels} 声道` : "等待中"}</dd>
        </div>
        <div>
          <dt>静默超时</dt>
          <dd>{audio?.realtime_input_idle_timeout_seconds ?? 0}s</dd>
        </div>
      </dl>
      <button
        className="tool-button"
        type="button"
        onClick={() => sessionId && wsClient.send(createEvent("client.debug.ping", sessionId, {}))}
      >
        <PlugZap size={18} />
        心跳测试
      </button>
    </section>
  );
}
