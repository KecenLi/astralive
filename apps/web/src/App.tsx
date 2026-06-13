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
  onResponseStarted?: () => void;
  onResponseFinished?: (reason: string) => void;
  onAssistantAudioDone?: () => void;
}

function cancelSpeech() {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  useAppStore.getState().setAvatarLipSync(0);
}

function speak(text: string, onDone?: () => void) {
  if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") return false;
  cancelSpeech();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  let lipTimer: number | null = null;
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    if (lipTimer) window.clearInterval(lipTimer);
    useAppStore.getState().setAvatarLipSync(0);
    onDone?.();
  };
  utterance.onstart = () => {
    const startedAt = performance.now();
    lipTimer = window.setInterval(() => {
      const level = 0.18 + Math.abs(Math.sin((performance.now() - startedAt) / 150)) * 0.35;
      useAppStore.getState().setAvatarLipSync(level);
    }, 90);
  };
  utterance.onend = utterance.onerror = finish;
  window.speechSynthesis.speak(utterance);
  return true;
}

function handleServerEvent(event: EventEnvelope<unknown>, effects: ServerEventEffects = {}) {
  const store = useAppStore.getState();
  if (event.type === "server.session.ready") {
    const payload = event.payload as { status?: string; audio?: AudioCapabilities; response_in_progress?: boolean };
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
    if (payload.response_in_progress) effects.onResponseStarted?.();
  }
  if (event.type === "server.session.state") {
    const payload = event.payload as { status?: string; audio?: AudioCapabilities; response_in_progress?: boolean };
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
    if (payload.response_in_progress) {
      effects.onResponseStarted?.();
    } else if (!assistantAudioPlayer.isActive()) {
      effects.onResponseFinished?.("server_state_idle");
    }
  }
  if (event.type === "assistant.text.delta") {
    effects.onResponseStarted?.();
    store.appendAssistantDelta((event.payload as { delta?: string }).delta ?? "");
  }
  if (event.type === "assistant.text.final") {
    const payload = event.payload as { text?: string; audio_expected?: boolean };
    const text = payload.text ?? "";
    effects.onResponseStarted?.();
    store.finalizeAssistant(text);
    if (!payload.audio_expected) {
      const speaking = speak(text, () => effects.onResponseFinished?.("speech_synthesis_done"));
      if (!speaking) effects.onResponseFinished?.("text_final_no_audio");
    }
  }
  if (event.type === "assistant.audio.chunk") {
    effects.onResponseStarted?.();
    cancelSpeech();
    void assistantAudioPlayer.play(event.payload as AssistantAudioPayload).catch((error) => {
      store.addMessage("system", error instanceof Error ? error.message : String(error));
      effects.onResponseFinished?.("audio_play_failed");
    });
  }
  if (event.type === "assistant.audio.done") {
    const payload = event.payload as { chunks?: number; fallback_text?: string };
    if ((payload.chunks ?? 0) === 0 && payload.fallback_text) {
      const speaking = speak(payload.fallback_text, () => effects.onResponseFinished?.("fallback_speech_done"));
      if (!speaking) effects.onResponseFinished?.("fallback_text_no_audio");
    } else {
      effects.onAssistantAudioDone?.();
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
    effects.onResponseFinished?.("server_error");
  }
}

function MainApp() {
  const store = useAppStore();
  const [audioStopSignal, setAudioStopSignal] = useState(0);
  const [wakeListenSignal, setWakeListenSignal] = useState(0);
  const [deviceStartSignal, setDeviceStartSignal] = useState(0);
  const [liveAudioActive, setLiveAudioActive] = useState(false);
  const [voiceResponsePending, setVoiceResponsePending] = useState(false);
  const [conversationMode, setConversationMode] = useState(false);
  const [sessionRestartSignal, setSessionRestartSignal] = useState(0);
  const audioTurnActiveRef = useRef(false);
  const voiceResponsePendingRef = useRef(false);
  const conversationModeRef = useRef(false);
  const assistantAudioDoneRef = useRef(false);
  const restartListenTimerRef = useRef(0);
  const reconnectTimerRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);

  const providerLabel = useMemo(
    () => `${store.cost.mode.toUpperCase()} / runtime providers`,
    [store.cost.mode],
  );

  const stopClientAudio = useCallback(() => {
    cancelSpeech();
    assistantAudioPlayer.reset();
    audioTurnActiveRef.current = false;
    assistantAudioDoneRef.current = false;
    voiceResponsePendingRef.current = false;
    setVoiceResponsePending(false);
    useAppStore.getState().setUserSpeechDraft("");
    setAudioStopSignal((value) => value + 1);
  }, []);

  const setConversationActive = useCallback((active: boolean) => {
    conversationModeRef.current = active;
    setConversationMode(active);
    if (!active) {
      window.clearTimeout(restartListenTimerRef.current);
    }
  }, []);

  const markResponseStarted = useCallback(() => {
    voiceResponsePendingRef.current = true;
    setVoiceResponsePending(true);
  }, []);

  const rearmContinuousListening = useCallback((reason: string) => {
    window.clearTimeout(restartListenTimerRef.current);
    if (!conversationModeRef.current) return;
    const actions = useAppStore.getState();
    if (actions.connection !== "connected" || !actions.sessionId) return;
    restartListenTimerRef.current = window.setTimeout(() => {
      if (!conversationModeRef.current) return;
      const latest = useAppStore.getState();
      if (latest.connection !== "connected" || !latest.sessionId) return;
      console.warn(`MODVII mic rearm continuous listening: ${reason}`);
      setWakeListenSignal((value) => value + 1);
    }, 450);
  }, []);

  const markResponseFinished = useCallback(
    (reason: string) => {
      if (!voiceResponsePendingRef.current && !assistantAudioDoneRef.current) return;
      if (assistantAudioPlayer.isActive()) return;
      assistantAudioDoneRef.current = false;
      voiceResponsePendingRef.current = false;
      setVoiceResponsePending(false);
      rearmContinuousListening(reason);
    },
    [rearmContinuousListening],
  );

  const handleAssistantAudioDone = useCallback(() => {
    assistantAudioDoneRef.current = true;
    markResponseFinished("assistant_audio_done");
  }, [markResponseFinished]);

  const scheduleReconnect = useCallback(() => {
    window.clearTimeout(reconnectTimerRef.current);
    if (reconnectAttemptsRef.current >= 5) {
      useAppStore.getState().addMessage("system", "WebSocket 已断开，自动重连已达到上限。");
      return;
    }
    reconnectAttemptsRef.current += 1;
    reconnectTimerRef.current = window.setTimeout(() => {
      useAppStore.getState().setConnection("connecting");
      setSessionRestartSignal((value) => value + 1);
    }, 900);
  }, []);

  const handleDevicePermissionComplete = useCallback(() => {
    setDeviceStartSignal((value) => value + 1);
  }, []);

  useEffect(() => {
    assistantAudioPlayer.setLipSyncSink((level) => useAppStore.getState().setAvatarLipSync(level));
    assistantAudioPlayer.setIdleCallback(() => markResponseFinished("audio_playback_idle"));
    let cleanup: () => void = () => {};
    let disposed = false;
    async function bootstrap() {
      const actions = useAppStore.getState();
      actions.setConnection("connecting");
      try {
        const response = await fetch(`${API_BASE_URL}/api/session`, { method: "POST" });
        const session = await response.json();
        if (disposed) return;
        actions.setSession(session.session_id, session.wake_word ?? "小七");
        cleanup = wsClient.onEvent((event) =>
          handleServerEvent(event, {
            stopRealtimeAudio: stopClientAudio,
            onResponseStarted: markResponseStarted,
            onResponseFinished: markResponseFinished,
            onAssistantAudioDone: handleAssistantAudioDone,
          }),
        );
        const socket = wsClient.connect(session.session_id);
        socket.onopen = () => {
          reconnectAttemptsRef.current = 0;
          useAppStore.getState().setConnection("connected");
        };
        socket.onerror = () => useAppStore.getState().setConnection("error");
        socket.onclose = () => {
          if (disposed) return;
          useAppStore.getState().setConnection("idle");
          voiceResponsePendingRef.current = false;
          setVoiceResponsePending(false);
          useAppStore.getState().addMessage("system", "WebSocket 已断开，正在重连。");
          scheduleReconnect();
        };
      } catch {
        if (!disposed) {
          actions.setConnection("error");
          scheduleReconnect();
        }
      }
    }
    void bootstrap();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimerRef.current);
      assistantAudioPlayer.setLipSyncSink(null);
      assistantAudioPlayer.setIdleCallback(null);
      cleanup();
      wsClient.close();
    };
  }, [
    handleAssistantAudioDone,
    markResponseFinished,
    markResponseStarted,
    scheduleReconnect,
    sessionRestartSignal,
    stopClientAudio,
  ]);

  const wake = useCallback(() => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return false;
    cancelSpeech();
    assistantAudioPlayer.reset();
    assistantAudioDoneRef.current = false;
    voiceResponsePendingRef.current = false;
    setVoiceResponsePending(false);
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
      setConversationActive(true);
      setWakeListenSignal((value) => value + 1);
    }
  }, [setConversationActive, wake]);

  const sleep = useCallback(() => {
    setConversationActive(false);
    stopClientAudio();
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    wsClient.send(createEvent("client.wake.sleep", actions.sessionId, {}));
  }, [setConversationActive, stopClientAudio]);

  const interrupt = useCallback(() => {
    setConversationActive(false);
    stopClientAudio();
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    wsClient.send(createEvent("client.control.interrupt", actions.sessionId, {}));
  }, [setConversationActive, stopClientAudio]);

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
    assistantAudioDoneRef.current = false;
    voiceResponsePendingRef.current = false;
    setVoiceResponsePending(false);
    setConversationActive(false);
    setAudioStopSignal((value) => value + 1);
    actions.setUserSpeechDraft("");
    actions.addMessage("user", text);
    wsClient.send(createEvent("client.user.text", actions.sessionId, { text }));
  }, [setConversationActive]);

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
    const sent = wsClient.send(createEvent("client.media.audio_chunk", actions.sessionId, payload));
    if (sent && payload.is_final) {
      assistantAudioDoneRef.current = false;
      markResponseStarted();
    }
    return sent;
  }, [markResponseStarted]);

  useEffect(() => {
    return () => {
      window.clearTimeout(restartListenTimerRef.current);
      window.clearTimeout(reconnectTimerRef.current);
    };
  }, []);

  function handleFrameSent(frame: FramePayload) {
    store.setLastFrameInfo(`${frame.width}x${frame.height} / ${frame.capture_reason}`);
  }

  const mediaUploadSuspended =
    liveAudioActive ||
    voiceResponsePending ||
    store.status === "thinking" ||
    store.status === "speaking";

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
            {conversationMode ? "继续听" : "唤醒"}
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
            suspendAutoUpload={mediaUploadSuspended}
          />
          <ScreenCapturePanel
            autoStartSignal={deviceStartSignal}
            onFrameSent={handleFrameSent}
            suspendAutoUpload={mediaUploadSuspended}
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
