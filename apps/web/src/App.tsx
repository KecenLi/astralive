import { Activity, Bot, Moon, Play, Settings } from "lucide-react";
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
import { SettingsPanel } from "./components/SettingsPanel/SettingsPanel";
import { assistantAudioPlayer } from "./features/media/pcmPlayer";
import {
  nextRealSpeechInputActive,
  shouldSuspendVisualAutoUpload,
  SpeechInputTransition,
} from "./features/realtime/conversationGates";
import { shouldFinishResponseTurn } from "./features/realtime/responseAudioTurn";
import { shouldStopRealtimeAudioOnError } from "./features/realtime/serverErrorActions";
import { useDesktopSettings } from "./hooks/useDesktopSettings";
import { API_BASE_URL, APP_MODE } from "./lib/env";
import {
  AssistantAudioPayload,
  AudioChunkPayload,
  AvatarStatePayload,
  CostMeter,
  createEvent,
  EventEnvelope,
  FramePayload,
  SessionStatePayload,
  VisionNeedFocusPayload,
} from "./lib/events";
import { wsClient } from "./lib/wsClient";

const RESPONSE_AUDIO_DONE_TIMEOUT_MS = 90_000;
const RESPONSE_TOTAL_WATCHDOG_TIMEOUT_MS = 90_000;
const FIXED_NOTICE_AUDIO_SOURCE = "fixed_notice";

const costModeLabel: Record<string, string> = {
  sleep: "睡眠模式",
  low_cost: "省流模式",
  active: "活跃模式",
  focus: "高清凝视",
};

const frameReasonLabel: Record<FramePayload["capture_reason"], string> = {
  wake_snapshot: "唤醒快照",
  visual_question: "视觉提问",
  scene_changed: "场景变化",
  manual_debug: "手动测试",
  focus_roi: "摄像头高清",
  periodic_low_cost: "低频采样",
  screen_low_fps: "屏幕低帧",
  screen_stream: "屏幕连续",
  camera_stream: "摄像头连续",
  screen_focus: "屏幕高清",
};

interface SendUserTextOptions {
  keepConversation?: boolean;
  proactive?: boolean;
  visibleText?: string;
}

interface ResponseFinishedOptions {
  force?: boolean;
  resetPlayback?: boolean;
  turnId?: number;
}

interface ServerEventEffects {
  stopRealtimeAudio?: () => void;
  onResponseStarted?: () => void;
  onResponseFinished?: (reason: string, options?: ResponseFinishedOptions) => void;
  onAssistantAudioExpected?: () => void;
  onAssistantAudioStreamDone?: () => void;
  onAssistantAudioDone?: () => void;
}

function cancelSpeech() {
  useAppStore.getState().setAvatarLipSync(0);
}

function handleServerEvent(event: EventEnvelope<unknown>, effects: ServerEventEffects = {}) {
  const store = useAppStore.getState();
  if (event.type === "server.session.ready") {
    const payload = event.payload as SessionStatePayload;
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
    if (payload.visual) store.setVisualCapabilities(payload.visual);
    store.setMemoryTurns(payload.history_turns);
    store.setVisualSelfCheckNotice(payload.visual_self_check_notice ?? payload.focus_notice);
    if (payload.response_in_progress) effects.onResponseStarted?.();
  }
  if (event.type === "server.session.state") {
    const payload = event.payload as SessionStatePayload;
    if (payload.status) store.setStatus(payload.status);
    if (payload.audio) store.setAudioCapabilities(payload.audio);
    if (payload.visual) store.setVisualCapabilities(payload.visual);
    store.setMemoryTurns(payload.history_turns);
    store.setVisualSelfCheckNotice(payload.visual_self_check_notice ?? payload.focus_notice);
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
    if (payload.audio_expected) {
      effects.onAssistantAudioExpected?.();
    } else {
      effects.onResponseFinished?.("text_final_no_audio");
    }
  }
  if (event.type === "assistant.audio.chunk") {
    const payload = event.payload as AssistantAudioPayload;
    const fixedNotice = payload.source === FIXED_NOTICE_AUDIO_SOURCE;
    if (!fixedNotice) {
      effects.onResponseStarted?.();
      effects.onAssistantAudioExpected?.();
    }
    cancelSpeech();
    void assistantAudioPlayer.play(payload).catch((error) => {
      store.addMessage("system", error instanceof Error ? error.message : String(error));
      if (!fixedNotice) effects.onResponseFinished?.("audio_play_failed");
    });
  }
  if (event.type === "assistant.audio.done") {
    const payload = event.payload as { chunks?: number; fallback_text?: string; source?: string };
    if (payload.source === FIXED_NOTICE_AUDIO_SOURCE) return;
    if ((payload.chunks ?? 0) === 0 && payload.fallback_text) {
      effects.onAssistantAudioDone?.();
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
    const payload = event.payload as {
      summary?: string;
      frame_id?: string;
      confidence?: number;
      need_focus?: boolean;
      focus_reason?: string | null;
    };
    store.setVisualSummary(payload.summary ?? "");
    store.setLastFrameInfo(`${payload.frame_id ?? "frame"} / ${(payload.confidence ?? 0).toFixed(2)}`);
    if (payload.need_focus) {
      store.setVisualSelfCheckNotice(
        payload.focus_reason ?? `视觉置信度 ${(payload.confidence ?? 0).toFixed(2)}，需要更清晰画面。`,
      );
    }
  }
  if (event.type === "vision.need_focus") {
    const payload = event.payload as VisionNeedFocusPayload;
    const confidence =
      typeof payload.confidence === "number" && Number.isFinite(payload.confidence)
        ? ` / ${(payload.confidence * 100).toFixed(0)}%`
        : "";
    const reason = payload.reason ?? payload.focus_reason ?? "需要更清晰画面";
    const notice = `${reason}${confidence}`;
    store.setVisualSelfCheckNotice(notice);
    store.addMessage("system", `${notice}，点击摄像头或屏幕的高清凝视按钮。`);
  }
  if (event.type === "vision.error") {
    const payload = event.payload as {
      frame_id?: string;
      capture_reason?: string;
      detail?: string;
      user_visible?: boolean;
    };
    const detail = payload.detail?.trim() || "视觉服务暂时不可用";
    store.setLastFrameInfo(`${payload.frame_id ?? "frame"} / 视觉失败`);
    if (payload.user_visible) {
      const reason =
        payload.capture_reason && payload.capture_reason in frameReasonLabel
          ? frameReasonLabel[payload.capture_reason as FramePayload["capture_reason"]]
          : "手动捕捉";
      store.setVisualSummary(`${reason}已上传，但云端视觉暂时失败：${detail}`);
      store.setVisualSelfCheckNotice("视觉云端失败，不是摄像头或屏幕权限问题。");
      store.addMessage("system", `视觉捕捉失败：${detail}。可以稍后重试，或先继续语音对话。`);
    }
  }
  if (event.type === "cost.update") {
    store.setCost(event.payload as unknown as CostMeter);
  }
  if (event.type === "error") {
    store.addMessage("system", JSON.stringify(event.payload));
    effects.onResponseFinished?.("server_error", { force: true, resetPlayback: true });
    if (shouldStopRealtimeAudioOnError(event.payload)) {
      effects.stopRealtimeAudio?.();
    }
  }
}

function MainApp() {
  const store = useAppStore();
  const [audioStopSignal, setAudioStopSignal] = useState(0);
  const [wakeListenSignal, setWakeListenSignal] = useState(0);
  const [keywordListenSignal, setKeywordListenSignal] = useState(0);
  const [deviceStartSignal, setDeviceStartSignal] = useState(0);
  const [liveAudioActive, setLiveAudioActive] = useState(false);
  const [realSpeechInputActive, setRealSpeechInputActive] = useState(false);
  const [voiceResponsePending, setVoiceResponsePending] = useState(false);
  const [conversationMode, setConversationMode] = useState(false);
  const [sessionRestartSignal, setSessionRestartSignal] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { settings: desktopSettings, patchSettings } = useDesktopSettings();
  const audioTurnActiveRef = useRef(false);
  const realSpeechInputActiveRef = useRef(false);
  const voiceResponsePendingRef = useRef(false);
  const conversationModeRef = useRef(false);
  const listenModeRef = useRef<"keyword" | "live">("keyword");
  const assistantAudioDoneRef = useRef(false);
  const responseAudioTurnInProgressRef = useRef(false);
  const restartListenTimerRef = useRef(0);
  const reconnectTimerRef = useRef(0);
  const proactiveTimerRef = useRef(0);
  const responseAudioDoneTimeoutRef = useRef(0);
  const responseTotalWatchdogRef = useRef(0);
  const responseTurnSerialRef = useRef(0);
  const activeResponseTurnIdRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);

  const providerLabel = useMemo(
    () => `${costModeLabel[store.cost.mode] ?? store.cost.mode} / 运行中模型`,
    [store.cost.mode],
  );

  const updateRealSpeechInput = useCallback((transition: SpeechInputTransition) => {
    const next = nextRealSpeechInputActive(realSpeechInputActiveRef.current, transition);
    if (next === realSpeechInputActiveRef.current) return;
    realSpeechInputActiveRef.current = next;
    setRealSpeechInputActive(next);
  }, []);

  const clearResponseTracking = useCallback(() => {
    audioTurnActiveRef.current = false;
    assistantAudioDoneRef.current = false;
    responseAudioTurnInProgressRef.current = false;
    activeResponseTurnIdRef.current = 0;
    window.clearTimeout(responseAudioDoneTimeoutRef.current);
    window.clearTimeout(responseTotalWatchdogRef.current);
    voiceResponsePendingRef.current = false;
    setVoiceResponsePending(false);
  }, []);

  const stopClientAudio = useCallback(() => {
    cancelSpeech();
    assistantAudioPlayer.reset();
    clearResponseTracking();
    updateRealSpeechInput({ type: "cancel" });
    useAppStore.getState().setUserSpeechDraft("");
    setAudioStopSignal((value) => value + 1);
  }, [clearResponseTracking, updateRealSpeechInput]);

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
      if (listenModeRef.current === "keyword") {
        setKeywordListenSignal((value) => value + 1);
      } else {
        setWakeListenSignal((value) => value + 1);
      }
    }, 450);
  }, []);

  const finishResponseAndRearm = useCallback(
    (reason: string, options: ResponseFinishedOptions = {}) => {
      if (typeof options.turnId === "number" && activeResponseTurnIdRef.current !== options.turnId) {
        return false;
      }
      const hasResponseState =
        voiceResponsePendingRef.current ||
        assistantAudioDoneRef.current ||
        responseAudioTurnInProgressRef.current ||
        activeResponseTurnIdRef.current > 0;
      if (!hasResponseState) return false;
      if (
        !shouldFinishResponseTurn({
          voiceResponsePending: voiceResponsePendingRef.current,
          assistantAudioDone: assistantAudioDoneRef.current,
          responseAudioTurnInProgress: responseAudioTurnInProgressRef.current,
          playerActive: assistantAudioPlayer.isActive(),
          force: options.force,
        })
      ) {
        return false;
      }
      if (options.resetPlayback) {
        cancelSpeech();
        assistantAudioPlayer.reset();
      }
      clearResponseTracking();
      rearmContinuousListening(reason);
      return true;
    },
    [clearResponseTracking, rearmContinuousListening],
  );

  const startResponseTotalWatchdog = useCallback(() => {
    window.clearTimeout(responseTotalWatchdogRef.current);
    const turnId = responseTurnSerialRef.current + 1;
    responseTurnSerialRef.current = turnId;
    activeResponseTurnIdRef.current = turnId;
    responseTotalWatchdogRef.current = window.setTimeout(() => {
      if (activeResponseTurnIdRef.current !== turnId) return;
      const reason = "response_total_watchdog_timeout";
      console.warn(`MODVII response total watchdog fired after ${RESPONSE_TOTAL_WATCHDOG_TIMEOUT_MS}ms`);
      useAppStore
        .getState()
        .addMessage("system", "连续对话等待服务端回应超时，已清理等待状态并重新开启监听。");
      finishResponseAndRearm(reason, { force: true, resetPlayback: true, turnId });
    }, RESPONSE_TOTAL_WATCHDOG_TIMEOUT_MS);
  }, [finishResponseAndRearm]);

  const markAssistantAudioExpected = useCallback(() => {
    window.clearTimeout(responseAudioDoneTimeoutRef.current);
    assistantAudioDoneRef.current = false;
    responseAudioTurnInProgressRef.current = true;
    responseAudioDoneTimeoutRef.current = window.setTimeout(() => {
      if (!responseAudioTurnInProgressRef.current) return;
      console.warn(`MODVII assistant audio.done watchdog fired after ${RESPONSE_AUDIO_DONE_TIMEOUT_MS}ms`);
      responseAudioTurnInProgressRef.current = false;
      assistantAudioDoneRef.current = true;
      finishResponseAndRearm("assistant_audio_done_timeout");
    }, RESPONSE_AUDIO_DONE_TIMEOUT_MS);
  }, [finishResponseAndRearm]);

  const markAssistantAudioStreamDone = useCallback(() => {
    window.clearTimeout(responseAudioDoneTimeoutRef.current);
    responseAudioTurnInProgressRef.current = false;
  }, []);

  const handleAssistantAudioDone = useCallback(() => {
    window.clearTimeout(responseAudioDoneTimeoutRef.current);
    responseAudioTurnInProgressRef.current = false;
    assistantAudioDoneRef.current = true;
    finishResponseAndRearm("assistant_audio_done");
  }, [finishResponseAndRearm]);

  const handleAssistantAudioIdle = useCallback(() => {
    if (responseAudioTurnInProgressRef.current) return;
    finishResponseAndRearm("audio_playback_idle");
  }, [finishResponseAndRearm]);

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
    assistantAudioPlayer.setIdleCallback(handleAssistantAudioIdle);
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
        actions.setMemoryTurns(session.history_turns);
        actions.setVisualSelfCheckNotice(session.visual_self_check_notice ?? session.focus_notice);
        cleanup = wsClient.onEvent((event) =>
          handleServerEvent(event, {
            stopRealtimeAudio: stopClientAudio,
            onResponseStarted: markResponseStarted,
            onResponseFinished: finishResponseAndRearm,
            onAssistantAudioExpected: markAssistantAudioExpected,
            onAssistantAudioStreamDone: markAssistantAudioStreamDone,
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
          clearResponseTracking();
          updateRealSpeechInput({ type: "error" });
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
      window.clearTimeout(responseAudioDoneTimeoutRef.current);
      window.clearTimeout(responseTotalWatchdogRef.current);
      assistantAudioPlayer.setLipSyncSink(null);
      assistantAudioPlayer.setIdleCallback(null);
      cleanup();
      wsClient.close();
    };
  }, [
    handleAssistantAudioDone,
    handleAssistantAudioIdle,
    clearResponseTracking,
    finishResponseAndRearm,
    markAssistantAudioExpected,
    markAssistantAudioStreamDone,
    markResponseStarted,
    scheduleReconnect,
    sessionRestartSignal,
    stopClientAudio,
    updateRealSpeechInput,
  ]);

  const wake = useCallback(() => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return false;
    cancelSpeech();
    assistantAudioPlayer.reset();
    clearResponseTracking();
    updateRealSpeechInput({ type: "cancel" });
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
  }, [clearResponseTracking, updateRealSpeechInput]);

  const wakeAndListen = useCallback(() => {
    listenModeRef.current = "keyword";
    setConversationActive(true);
    setKeywordListenSignal((value) => value + 1);
  }, [setConversationActive]);

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

  const sendUserText = useCallback((text: string, options: SendUserTextOptions = {}) => {
    const actions = useAppStore.getState();
    if (!actions.sessionId) return;
    cancelSpeech();
    assistantAudioPlayer.reset();
    clearResponseTracking();
    updateRealSpeechInput({ type: "cancel" });
    setConversationActive(Boolean(options.keepConversation));
    if (!options.keepConversation) {
      listenModeRef.current = "keyword";
      setAudioStopSignal((value) => value + 1);
    }
    actions.setUserSpeechDraft("");
    if (options.proactive) {
      actions.addMessage("system", options.visibleText || "小七主动发起了一个话题。");
    } else {
      actions.addMessage("user", text);
    }
    wsClient.send(createEvent("client.user.text", actions.sessionId, { text, proactive: Boolean(options.proactive) }));
  }, [clearResponseTracking, setConversationActive, updateRealSpeechInput]);

  useEffect(() => {
    return window.modvii?.pet.onProactiveAccepted?.((payload) => {
      const prompt =
        payload.prompt ||
        "请以 MODVII 小七的身份主动开启一个简短自然的话题，语气轻快，最多两句话。";
      sendUserText(prompt, {
        proactive: true,
        visibleText: payload.text || "桌宠小七接入了一个主动话题。",
      });
    }) ?? (() => undefined);
  }, [sendUserText]);

  useEffect(() => {
    window.clearTimeout(proactiveTimerRef.current);
    const proactive = desktopSettings.proactiveChat;
    if (!proactive.enabled) return () => undefined;

    const schedule = () => {
      const minMs = proactive.minIntervalMinutes * 60_000;
      const maxMs = proactive.maxIntervalMinutes * 60_000;
      const delayMs = minMs + Math.random() * Math.max(0, maxMs - minMs);
      proactiveTimerRef.current = window.setTimeout(() => {
        const latest = useAppStore.getState();
        const busy =
          latest.connection !== "connected" ||
          !latest.sessionId ||
          conversationModeRef.current ||
          liveAudioActive ||
          voiceResponsePendingRef.current ||
          assistantAudioPlayer.isActive() ||
          latest.status === "thinking" ||
          latest.status === "speaking";

        if (!busy) {
          const payload = {
            text: "我有个小想法，点我聊一下。",
            prompt:
              "请以 MODVII 小七的身份主动开启一个简短自然的话题，结合当前上下文但不要假装看到不存在的信息，最多两句话。",
          };
          if (proactive.petBubbleFirst && window.modvii?.pet.notify) {
            void window.modvii.pet.notify(payload).catch(() => {
              sendUserText(payload.prompt, { proactive: true, visibleText: payload.text });
            });
          } else {
            sendUserText(payload.prompt, { proactive: true, visibleText: payload.text });
          }
        }
        schedule();
      }, delayMs);
    };

    schedule();
    return () => window.clearTimeout(proactiveTimerRef.current);
  }, [
    desktopSettings.proactiveChat,
    liveAudioActive,
    sendUserText,
  ]);

  const sendAudioChunk = useCallback((payload: AudioChunkPayload) => {
    const actions = useAppStore.getState();
    if (payload.is_final) {
      updateRealSpeechInput({ type: "audio_final" });
    } else if (payload.data_base64) {
      updateRealSpeechInput({ type: "audio_chunk", isFinal: false, hasAudio: true });
    }
    if (!actions.sessionId) return false;
    if (!payload.is_final && !audioTurnActiveRef.current) {
      cancelSpeech();
      assistantAudioPlayer.reset();
      clearResponseTracking();
      actions.setUserSpeechDraft("");
      audioTurnActiveRef.current = true;
    }
    if (payload.is_final) {
      audioTurnActiveRef.current = false;
    }
    const sent = wsClient.send(createEvent("client.media.audio_chunk", actions.sessionId, payload));
    if (sent && payload.is_final) {
      assistantAudioDoneRef.current = false;
      responseAudioTurnInProgressRef.current = false;
      window.clearTimeout(responseAudioDoneTimeoutRef.current);
      markResponseStarted();
      startResponseTotalWatchdog();
    }
    return sent;
  }, [clearResponseTracking, markResponseStarted, startResponseTotalWatchdog, updateRealSpeechInput]);

  const handleSpeechInputStateChange = useCallback(
    (active: boolean, reason: string) => {
      if (active) {
        updateRealSpeechInput({ type: "speech_start" });
        return;
      }
      if (reason === "audio_final") {
        updateRealSpeechInput({ type: "audio_final" });
      } else if (reason === "error") {
        updateRealSpeechInput({ type: "error" });
      } else if (reason === "cancel") {
        updateRealSpeechInput({ type: "cancel" });
      } else {
        updateRealSpeechInput({ type: "stop" });
      }
    },
    [updateRealSpeechInput],
  );

  useEffect(() => {
    return () => {
      window.clearTimeout(restartListenTimerRef.current);
      window.clearTimeout(reconnectTimerRef.current);
      window.clearTimeout(proactiveTimerRef.current);
      window.clearTimeout(responseAudioDoneTimeoutRef.current);
      window.clearTimeout(responseTotalWatchdogRef.current);
    };
  }, []);

  function handleFrameSent(frame: FramePayload) {
    store.setLastFrameInfo(`${frame.width}x${frame.height} / ${frameReasonLabel[frame.capture_reason] ?? frame.capture_reason}`);
  }

  const mediaUploadSuspended = shouldSuspendVisualAutoUpload({
    realSpeechInputActive,
    conversationMode,
    liveAudioActive,
    voiceResponsePending,
    status: store.status,
  });

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
            {conversationMode ? "监听中" : "监听小七"}
          </button>
          <button className="tool-button subtle" type="button" onClick={sleep}>
            <Moon size={18} />
            睡眠
          </button>
          <button className="tool-button subtle" type="button" onClick={togglePet} data-testid="toggle-pet">
            <Bot size={18} />
            桌宠
          </button>
          <button className="tool-button subtle" type="button" onClick={() => setSettingsOpen(true)}>
            <Settings size={18} />
            设置
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
            keywordListenSignal={keywordListenSignal}
            settings={desktopSettings.voice}
            onWake={wake}
            onUserText={sendUserText}
            onAudioChunk={sendAudioChunk}
            onLiveStateChange={setLiveAudioActive}
            onSpeechInputStateChange={handleSpeechInputStateChange}
            stopSignal={audioStopSignal}
          />
          <CostPanel />
          <DebugPanel />
        </aside>
        <section className="main-stage">
          <AvatarStage onInterrupt={interrupt} layout={desktopSettings.avatarLayout.main} />
        </section>
      </div>

      <ConversationPanel />
      <SettingsPanel
        open={settingsOpen}
        settings={desktopSettings}
        onClose={() => setSettingsOpen(false)}
        onPatch={(patch) => {
          void patchSettings(patch).catch((error) => {
            useAppStore
              .getState()
              .addMessage("system", error instanceof Error ? error.message : "设置保存失败。");
          });
        }}
      />
    </main>
  );
}

export default function App() {
  return APP_MODE === "pet" ? <DesktopPet /> : <MainApp />;
}
