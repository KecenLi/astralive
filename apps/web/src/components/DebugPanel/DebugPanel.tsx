import { Bug, PlugZap } from "lucide-react";

import { useAppStore } from "../../app/store";
import { createEvent } from "../../lib/events";
import { wsClient } from "../../lib/wsClient";

export function DebugPanel() {
  const connection = useAppStore((state) => state.connection);
  const sessionId = useAppStore((state) => state.sessionId);

  return (
    <section className="panel debug-panel">
      <div className="panel-title">
        <Bug size={18} />
        <span>Debug</span>
      </div>
      <dl className="metric-list">
        <div>
          <dt>连接</dt>
          <dd>{connection}</dd>
        </div>
        <div>
          <dt>Session</dt>
          <dd>{sessionId || "pending"}</dd>
        </div>
      </dl>
      <button
        className="tool-button"
        type="button"
        onClick={() => sessionId && wsClient.send(createEvent("client.debug.ping", sessionId, {}))}
      >
        <PlugZap size={18} />
        Ping
      </button>
    </section>
  );
}

