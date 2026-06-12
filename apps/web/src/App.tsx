import { Activity, Moon, Play } from "lucide-react";
import { useEffect, useMemo } from "react";

import { useAppStore } from "./app/store";
import { AvatarStage } from "./components/AvatarStage/AvatarStage";
import { CameraPanel } from "./components/CameraPanel/CameraPanel";
import { ConversationPanel } from "./components/ConversationPanel/ConversationPanel";
import { CostPanel } from "./components/CostPanel/CostPanel";
import { DebugPanel } from "./components/DebugPanel/DebugPanel";
import { MicPanel } from "./components/MicPanel/MicPanel";
import { API_BASE_URL } from "./lib/env";
import { AvatarStatePayload, CostMeter, createEvent, EventEnvelope, FramePayload } from "./lib/events";
import { wsClient } from "./lib/wsClient";

function speak(text: string) {
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

function handleServerEvent(event: EventEnvelope<unknown>) {
  const store = useAppStore.getState();
  if (event.type === "server.session.state") {
    const payload = event.payload as { status?: string };
    if (payload.status) store.setStatus(payload.status);
  }
  if (event.type === "assistant.text.delta") {
    store.appendAssistantDelta((event.payload as { delta?: string }).delta ?? "");
  }
  if (event.type === "assistant.text.final") {
    const text = (event.payload as { text?: string }).text ?? "";
    store.finalizeAssistant(text);
    speak(text);
  }
  if (event.type === "assistant.avatar.state") {
    store.setAvatar(event.payload as unknown as AvatarStatePayload);
  }
  if (event.type === "vision.summary") {
    const payload = event.payload as { summary?: string; frame_id?: string; confidence?: number };
    store.setVisualSummary(payload.summary ?? "");
    store.setLastFrameInfo(`${payload.frame_id ?? "frame"} / ${(payload.confidence ?? 0).toFixed(2)}`);
  }
  if (event.type === "vision.need_focus") {
    store.addMessage("system", "需要更清晰画面，点击 Camera 的高清凝视按钮。");
  }
  if (event.type === "cost.update") {
    store.setCost(event.payload as unknown as CostMeter);
  }
  if (event.type === "error") {
    store.addMessage("system", JSON.stringify(event.payload));
  }
}

export default function App() {
  const store = useAppStore();

  const providerLabel = useMemo(
    () => `${store.cost.mode.toUpperCase()} / mock providers`,
    [store.cost.mode],
  );

  useEffect(() => {
    let cleanup: () => void = () => {};
    async function bootstrap() {
      const actions = useAppStore.getState();
      actions.setConnection("connecting");
      try {
        const response = await fetch(`${API_BASE_URL}/api/session`, { method: "POST" });
        const session = await response.json();
        actions.setSession(session.session_id, session.wake_word ?? "阿斯塔");
        const socket = wsClient.connect(session.session_id);
        socket.onopen = () => useAppStore.getState().setConnection("connected");
        socket.onerror = () => useAppStore.getState().setConnection("error");
        socket.onclose = () => useAppStore.getState().setConnection("idle");
        cleanup = wsClient.onEvent(handleServerEvent);
      } catch {
        actions.setConnection("error");
      }
    }
    void bootstrap();
    return () => {
      cleanup();
      wsClient.close();
    };
  }, []);

  function wake() {
    if (!store.sessionId) return;
    store.markWake();
    store.addMessage("system", `已听到唤醒词：${store.wakeWord}`);
    wsClient.send(createEvent("client.wake.detected", store.sessionId, { wake_word: store.wakeWord }));
  }

  function sleep() {
    window.speechSynthesis.cancel();
    if (!store.sessionId) return;
    wsClient.send(createEvent("client.wake.sleep", store.sessionId, {}));
  }

  function interrupt() {
    window.speechSynthesis.cancel();
    if (!store.sessionId) return;
    wsClient.send(createEvent("client.control.interrupt", store.sessionId, {}));
  }

  function sendUserText(text: string) {
    if (!store.sessionId) return;
    store.addMessage("user", text);
    wsClient.send(createEvent("client.user.text", store.sessionId, { text }));
  }

  function handleFrameSent(frame: FramePayload) {
    store.setLastFrameInfo(`${frame.width}x${frame.height} / ${frame.capture_reason}`);
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div className="brand">
          <Activity size={22} />
          <div>
            <h1>AstraLive</h1>
            <span>{providerLabel}</span>
          </div>
        </div>
        <div className="top-actions">
          <button className="tool-button" type="button" onClick={wake}>
            <Play size={18} />
            唤醒
          </button>
          <button className="tool-button subtle" type="button" onClick={sleep}>
            <Moon size={18} />
            睡眠
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="left-rail">
          <CameraPanel onFrameSent={handleFrameSent} />
          <MicPanel onWake={wake} onUserText={sendUserText} />
          <CostPanel />
          <DebugPanel />
        </aside>
        <section className="main-stage">
          <AvatarStage onInterrupt={interrupt} />
        </section>
      </div>

      <ConversationPanel />
    </main>
  );
}
