import { Activity, Bot, Moon, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAppStore } from "./app/store";
import { AvatarStage } from "./components/AvatarStage/AvatarStage";
import { CameraPanel } from "./components/CameraPanel/CameraPanel";
import { ConversationPanel } from "./components/ConversationPanel/ConversationPanel";
import { CostPanel } from "./components/CostPanel/CostPanel";
import { DesktopPet } from "./components/DesktopPet/DesktopPet";
import { DevicePermissionWizard } from "./components/DevicePermissionWizard/DevicePermissionWizard";
import { DebugPanel } from "./components/DebugPanel/DebugPanel";
import { MicPanel } from "./components/MicPanel/MicPanel";
import { ScreenCapturePanel } from "./components/ScreenCapturePanel/ScreenCapturePanel";
import { assistantAudioPlayer } from "./features/media/pcmPlayer";
import { shouldStopRealtimeAudioOnError } from "./features/realtime/serverErrorActions";
import { API_BASE_URL, APP_MODE } from "./lib/env";
import {
  AudioCapabilities,
  AssistantAudioPayload,
  AudioChunkPayload,
  AvatarStatePayload,
  CostMeter,
  createEvent,
  EventEnvelope,
  FramePayload,
} from "./lib/events";
import { wsClient } from "./lib/wsClient";

interface ServerEventEffects {
  stopRealtimeAudio?: () => void;
}

function cancelSpeech() {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  useAppStore.getState().setAvatarLipSync(0);
}

function speak(text: string) {
  if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return;
  cancelSpeech();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  let lipTimer: number | null = null;
  utterance.onstart = () => {
    const startedAt = performance.now();
    lipTimer = window.setInterval(() => {
      const level = 0.18 + Math.abs(Math.sin((performance.now() - startedAt) / 150)) * 0.35;
      useAppStore.getState().setAvatarLipSync(level);
    }, 90);
  };
  utterance.onend = utterance.onerror = () => {
    if (lipTimer) window.clearInterval(lipTimer);
    useAppStore.getState().setAvatarLipSync(0);
  };
  window.speechSynthesis.speak(utterance);
}

function handleServerEvent(event: EventEnvelope<unknown>, effects: ServerEventEffects = {}) {
  const store = useAppStore.getState();
  if (event.type === "server.session.ready") {
    const payload = event.payload as { status?: string; audio?: AudioCapabilities };
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
  }
  if (event.type === "server.session.state") {
    const payload = event.payload as { status?: string; audio?: AudioCapabilities };
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
  }
  if (event.type === "assistant.text.delta") {
    store.appendAssistantDelta((event.payload as { delta?: string }).delta ?? "");
  }
  if (event.type === "assistant.text.final") {
    const payload = event.payload as { text?: string; audio_expected?: boolean };
    const text = payload.text ?? "";
    store.finalizeAssistant(text);
    if (!payload.audio_expected) speak(text);
  }
  if (event.type === "assistant.audio.chunk") {
    cancelSpeech();
    void assistantAudioPlayer.play(event.payload as AssistantAudioPayload).catch((error) => {
      store.addMessage("system", error instanceof Error ? error.message : String(error));
    });
  }
  if (event.type === "assistant.audio.done") {
    const payload = event.payload as { chunks?: number; fallback_text?: string };
    if ((payload.chunks ?? 0) === 0 && payload.fallback_text) {
      speak(payload.fallback_text);
    }
  }
  if (event.type === "assistant.avatar.state") {
    store.setAvatar(event.payload as unknown as AvatarStatePayload);
  }
  if (event.type === "asr.transcript.partial") {
    const text = (event.payload as { text?: string }).text?.trim();
    if (text) store.setUserSpeechDraft(text);
  }
  if (event.type === "asr.transcript.final") {
    const text = (event.payload as { text?: string }).text?.trim();
    store.finalizeUserSpeech(text ?? "");
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
    if (shouldStopRealtimeAudioOnError(event.payload)) {
      effects.stopRealtimeAudio?.();
    }
  }
}

function MainApp() {
  const store = useAppStore();
  const [audioStopSignal, setAudioStopSignal] = useState(0);
  const [wakeListenSignal, setWakeListenSignal] = useState(0);
  const [deviceStartSignal, setDeviceStartSignal] = useState(0);
  const [liveAudioActive, setLiveAudioActive] = useState(false);
  const audioTurnActiveRef = useRef(false);

  const providerLabel = useMemo(
    () => `${store.cost.mode.toUpperCase()} / runtime providers`,
    [store.cost.mode],
  );

  const stopClientAudio = useCallback(() => {
    cancelSpeech();
    assistantAudioPlayer.reset();
    audioTurnActiveRef.current = false;
    useAppStore.getState().setUserSpeechDraft("");
    setAudioStopSignal((value) => value + 1);
  }, []);

  const handleDevicePermissionComplete = useCallback(() => {
    setDeviceStartSignal((value) => value + 1);
  }, []);

  useEffect(() => {
    assistantAudioPlayer.setLipSyncSink((level) => useAppStore.getState().setAvatarLipSync(level));
    let cleanup: () => void = () => {};
    async function bootstrap() {
      const actions = useAppStore.getState();
      actions.setConnection("connecting");
      try {
        const response = await fetch(`${API_BASE_URL}/api/session`, { method: "POST" });
        const session = await response.json();
        actions.setSession(session.session_id, session.wake_word ?? "小七");
        cleanup = wsClient.onEvent((event) => handleServerEvent(event, { stopRealtimeAudio: stopClientAudio }));
        const socket = wsClient.connect(session.session_id);
        socket.onopen = () => useAppStore.getState().setConnection("connected");
        socket.onerror = () => useAppStore.getState().setConnection("error");
        socket.onclose = () => useAppStore.getState().setConnection("idle");
      } catch {
        actions.setConnection("error");
      }
    }
    void bootstrap();
    return () => {
      assistantAudioPlayer.setLipSyncSink(null);
      cleanup();
      wsClient.close();
    };
  }, [stopClientAudio]);

  const wake = useCallback(() => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return false;
    cancelSpeech();
    assistantAudioPlayer.reset();
    const sent = wsClient.send(
      createEvent("client.wake.detected", actions.sessionId, { wake_word: actions.wakeWord }),
    );
    if (!sent) {
      actions.addMessage("system", "WebSocket 未连接，唤醒未发送。");
      return false;
    }
    actions.markWake();
    actions.addMessage("system", `已听到唤醒词：${actions.wakeWord}`);
    return true;
  }, []);

  const wakeAndListen = useCallback(() => {
    if (wake()) {
      setWakeListenSignal((value) => value + 1);
    }
  }, [wake]);

  const sleep = useCallback(() => {
    stopClientAudio();
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    wsClient.send(createEvent("client.wake.sleep", actions.sessionId, {}));
  }, [stopClientAudio]);

  const interrupt = useCallback(() => {
    stopClientAudio();
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    wsClient.send(createEvent("client.control.interrupt", actions.sessionId, {}));
  }, [stopClientAudio]);

  const togglePet = useCallback(() => {
    const actions = useAppStore.getState();
    if (!window.modvii?.pet) {
      actions.addMessage("system", "桌宠窗口只在 Windows exe 中可用。");
      return;
    }
    void window.modvii.pet.toggle().catch((error) => {
      actions.addMessage("system", error instanceof Error ? error.message : "桌宠窗口打开失败。");
    });
  }, []);

  const sendUserText = useCallback((text: string) => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    cancelSpeech();
    assistantAudioPlayer.reset();
    audioTurnActiveRef.current = false;
    setAudioStopSignal((value) => value + 1);
    actions.setUserSpeechDraft("");
    actions.addMessage("user", text);
    wsClient.send(createEvent("client.user.text", actions.sessionId, { text }));
  }, []);

  const sendAudioChunk = useCallback((payload: AudioChunkPayload) => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return false;
    if (!payload.is_final && !audioTurnActiveRef.current) {
      cancelSpeech();
      assistantAudioPlayer.reset();
      actions.setUserSpeechDraft("");
      audioTurnActiveRef.current = true;
    }
    if (payload.is_final) {
      audioTurnActiveRef.current = false;
    }
    return wsClient.send(createEvent("client.media.audio_chunk", actions.sessionId, payload));
  }, []);

  function handleFrameSent(frame: FramePayload) {
    store.setLastFrameInfo(`${frame.width}x${frame.height} / ${frame.capture_reason}`);
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div className="brand">
          <Activity size={22} />
          <div>
            <h1>MODVII</h1>
            <span>{providerLabel}</span>
          </div>
        </div>
        <div className="top-actions">
          <button className="tool-button" type="button" onClick={wakeAndListen}>
            <Play size={18} />
            唤醒
          </button>
          <button className="tool-button subtle" type="button" onClick={sleep}>
            <Moon size={18} />
            睡眠
          </button>
          <button className="tool-button subtle" type="button" onClick={togglePet} data-testid="toggle-pet">
            <Bot size={18} />
            桌宠
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="left-rail">
          <DevicePermissionWizard onComplete={handleDevicePermissionComplete} />
          <CameraPanel
            autoStartSignal={deviceStartSignal}
            onFrameSent={handleFrameSent}
            suspendAutoUpload={liveAudioActive}
          />
          <ScreenCapturePanel
            autoStartSignal={deviceStartSignal}
            onFrameSent={handleFrameSent}
            suspendAutoUpload={liveAudioActive}
          />
          <MicPanel
            autoStartSignal={deviceStartSignal}
            wakeListenSignal={wakeListenSignal}
            onWake={wake}
            onUserText={sendUserText}
            onAudioChunk={sendAudioChunk}
            onLiveStateChange={setLiveAudioActive}
            stopSignal={audioStopSignal}
          />
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

export default function App() {
  return APP_MODE === "pet" ? <DesktopPet /> : <MainApp />;
}
