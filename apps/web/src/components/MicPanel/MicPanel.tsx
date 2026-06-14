import { AudioLines, Mic, MicOff, Radio, Send, Square } from "lucide-react";
import { MicVAD } from "@ricky0123/vad-web";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import {
  arrayBufferToBase64,
  encodePcm16,
  LIVE_INPUT_SAMPLE_RATE,
  PcmRecorder,
  scalePcm16Buffer,
} from "../../features/media/pcmRecorder";
import { TenVadRecorder } from "../../features/media/tenVadRecorder";
import { LiveAudioGate, LiveAudioGateDecision } from "../../features/media/voiceActivity";
import { getSpeechRecognition, SpeechRecognition } from "../../features/wakeword/speechRecognition";
import { DEFAULT_VOICE_SETTINGS, VoiceSettings } from "../../lib/desktopSettings";
import { extractWakeRequest } from "../../features/wakeword/wakePhrase";
import { AudioChunkPayload, createId } from "../../lib/events";

interface MicPanelProps {
  autoStartSignal: number;
  wakeListenSignal: number;
  keywordListenSignal: number;
  settings?: VoiceSettings;
  onWake: () => boolean | void;
  onUserText: (text: string, options?: { keepConversation?: boolean }) => void;
  onAudioChunk: (payload: AudioChunkPayload) => boolean;
  onLiveStateChange?: (active: boolean) => void;
  onSpeechInputStateChange?: (active: boolean, reason: string) => void;
  stopSignal: number;
}

const AUDIO_SEND_CHUNK_BYTES = 120_000;

function publicAssetBase(path: string) {
  return new URL(path, window.location.href).toString();
}

function splitPcm16Buffer(buffer: ArrayBuffer) {
  const chunks: ArrayBuffer[] = [];
  let offset = 0;
  while (offset < buffer.byteLength) {
    let end = Math.min(offset + AUDIO_SEND_CHUNK_BYTES, buffer.byteLength);
    if (end < buffer.byteLength && end % 2 !== 0) end -= 1;
    chunks.push(buffer.slice(offset, end));
    offset = end;
  }
  return chunks;
}

export function MicPanel({
  autoStartSignal,
  wakeListenSignal,
  keywordListenSignal,
  settings: voiceSettings = DEFAULT_VOICE_SETTINGS,
  onWake,
  onUserText,
  onAudioChunk,
  onLiveStateChange,
  onSpeechInputStateChange,
  stopSignal,
}: MicPanelProps) {
  const [micState, setMicState] = useState("未授权");
  const [muted, setMuted] = useState(false);
  const [level, setLevel] = useState(0);
  const [text, setText] = useState("");
  const [liveStreaming, setLiveStreaming] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const recorderRef = useRef<PcmRecorder | null>(null);
  const audioGateRef = useRef<LiveAudioGate | null>(null);
  const tenVadRecorderRef = useRef<TenVadRecorder | null>(null);
  const sileroVadRef = useRef<MicVAD | null>(null);
  const startLiveAudioRef = useRef<() => Promise<void>>(async () => undefined);
  const startWakeRecognitionRef = useRef<() => void>(() => undefined);
  const audioSentRef = useRef(false);
  const speechInputActiveRef = useRef(false);
  const traceIdRef = useRef("");
  const startingRef = useRef(false);
  const recognitionWantedRef = useRef(false);
  const recognitionRestartTimerRef = useRef(0);
  const pendingWakeTimerRef = useRef(0);
  const pendingWakeRequestRef = useRef("");
  const wakePendingRef = useRef(false);
  const handledWakeTranscriptRef = useRef("");
  const rafRef = useRef(0);
  const wakeAtRef = useRef(0);
  const [recognitionActive, setRecognitionActive] = useState(false);
  const sessionId = useAppStore((state) => state.sessionId);
  const connection = useAppStore((state) => state.connection);
  const wakeWord = useAppStore((state) => state.wakeWord);
  const audioCapabilities = useAppStore((state) => state.audioCapabilities);
  const realtimeAvailable = Boolean(audioCapabilities?.server_realtime_audio);
  const realtimeFormatCompatible = Boolean(
    audioCapabilities &&
      audioCapabilities.input_sample_rate === LIVE_INPUT_SAMPLE_RATE &&
      audioCapabilities.channels === 1,
  );
  const realtimeUnavailableReason = !sessionId
    ? "会话未就绪"
    : connection !== "connected"
      ? "WebSocket 未连接"
      : !realtimeAvailable
        ? "实时语音未启用"
        : !realtimeFormatCompatible
          ? "实时格式不匹配"
          : "";
  const realtimeReady = realtimeUnavailableReason === "";
  const liveButtonTitle = liveStreaming
    ? "结束实时语音"
    : realtimeReady
      ? "开始实时语音"
      : realtimeUnavailableReason;

  const setSpeechInputActive = useCallback(
    (active: boolean, reason: string) => {
      if (speechInputActiveRef.current === active) return;
      speechInputActiveRef.current = active;
      onSpeechInputStateChange?.(active, reason);
    },
    [onSpeechInputStateChange],
  );

  const stopMic = useCallback(() => {
    tenVadRecorderRef.current?.stop();
    tenVadRecorderRef.current = null;
    const vad = sileroVadRef.current;
    sileroVadRef.current = null;
    void vad?.destroy().catch((error) => {
      console.warn("MODVII mic Silero cleanup failed", error);
    });
    recorderRef.current?.stop();
    recorderRef.current = null;
    audioGateRef.current = null;
    audioSentRef.current = false;
    setSpeechInputActive(false, "stop");
    setLiveStreaming(false);
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setLevel(0);
  }, [setSpeechInputActive]);

  function stopWakeRecognition() {
    recognitionWantedRef.current = false;
    wakePendingRef.current = false;
    pendingWakeRequestRef.current = "";
    window.clearTimeout(recognitionRestartTimerRef.current);
    window.clearTimeout(pendingWakeTimerRef.current);
    recognitionRestartTimerRef.current = 0;
    pendingWakeTimerRef.current = 0;
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.stop();
      } catch {
        // Some browser implementations throw if stop() races with onend.
      }
    }
    setRecognitionActive(false);
  }

  const startMic = useCallback(async () => {
    try {
      stopMic();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: voiceSettings.echoCancellation,
          noiseSuppression: voiceSettings.noiseSuppression,
          autoGainControl: voiceSettings.autoGainControl,
          channelCount: 1,
          sampleRate: 48000,
        },
        video: false,
      });
      streamRef.current = stream;
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(data);
        const average = data.reduce((sum, value) => sum + value, 0) / data.length;
        setLevel(Math.min(1, average / 120));
        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
      setMicState("ready");
      return stream;
    } catch (error) {
      setMicState(error instanceof Error ? error.message : "麦克风不可用");
      return null;
    }
  }, [stopMic, voiceSettings.autoGainControl, voiceSettings.echoCancellation, voiceSettings.noiseSuppression]);

  const audioMetadata = useCallback(
    (extra: Record<string, unknown> = {}) => {
      if (!traceIdRef.current) traceIdRef.current = createId("turn");
      return {
        source: "browser_pcm",
        trace_id: traceIdRef.current,
        send_mode: voiceSettings.sendMode,
        vad_provider: voiceSettings.vadProvider,
        route: voiceSettings.route,
        client_sent_at: Date.now(),
        ...extra,
      };
    },
    [voiceSettings.route, voiceSettings.sendMode, voiceSettings.vadProvider],
  );

  const sendAudioChunk = useCallback((buffer: ArrayBuffer, isFinal: boolean, metadata: Record<string, unknown> = {}) => {
    if (!sessionId) {
      setSpeechInputActive(false, isFinal ? "audio_final" : "error");
      return false;
    }
    const payload: AudioChunkPayload = {
      chunk_id: createId("aud"),
      mime: `audio/pcm;rate=${LIVE_INPUT_SAMPLE_RATE}`,
      sample_rate: LIVE_INPUT_SAMPLE_RATE,
      channels: 1,
      encoding: "pcm_s16le",
      data_base64: buffer.byteLength > 0 ? arrayBufferToBase64(buffer) : "",
      is_final: isFinal,
      metadata: audioMetadata(metadata),
    };
    if (!isFinal && buffer.byteLength > 0) {
      setSpeechInputActive(true, "audio_chunk");
    }
    const sent = onAudioChunk(payload);
    if (isFinal) {
      setSpeechInputActive(false, "audio_final");
    } else if (!sent) {
      setSpeechInputActive(false, "error");
    }
    return sent;
  }, [audioMetadata, onAudioChunk, sessionId, setSpeechInputActive]);

  const sendAudioTurn = useCallback((buffer: ArrayBuffer) => {
    let sentAudio = false;
    let sentChunks = 0;
    for (const chunk of splitPcm16Buffer(buffer)) {
      const sent = sendAudioChunk(chunk, false);
      if (!sent) {
        return { sentAudio, sentFinal: false, sentChunks, totalBytes: buffer.byteLength };
      }
      sentAudio = true;
      sentChunks += 1;
    }
    return {
      sentAudio,
      sentFinal: sentAudio ? sendAudioChunk(new ArrayBuffer(0), true) : false,
      sentChunks,
      totalBytes: buffer.byteLength,
    };
  }, [sendAudioChunk]);

  const stopLiveAudio = useCallback(
    (sendFinal: boolean) => {
      const hadRecorder = Boolean(recorderRef.current);
      const hadTenVad = Boolean(tenVadRecorderRef.current);
      const hadSileroVad = Boolean(sileroVadRef.current);
      tenVadRecorderRef.current?.stop();
      tenVadRecorderRef.current = null;
      const vad = sileroVadRef.current;
      sileroVadRef.current = null;
      void vad?.destroy().catch((error) => {
        console.warn("MODVII mic Silero stop failed", error);
      });
      recorderRef.current?.stop();
      recorderRef.current = null;
      audioGateRef.current?.reset();
      audioGateRef.current = null;
      startingRef.current = false;
      setSpeechInputActive(false, "stop");
      setLiveStreaming(false);
      const shouldSendFinal = sendFinal && (hadRecorder || hadTenVad || hadSileroVad) && audioSentRef.current;
      if (shouldSendFinal) {
        const sent = sendAudioChunk(new ArrayBuffer(0), true);
        if (!sent) setMicState("WebSocket 未连接");
      }
      audioSentRef.current = false;
      traceIdRef.current = "";
      if (hadRecorder || hadTenVad || hadSileroVad) {
        setMicState("ready");
      }
    },
    [sendAudioChunk, setSpeechInputActive],
  );

  async function startLiveAudio() {
    if (liveStreaming || recorderRef.current || tenVadRecorderRef.current || sileroVadRef.current) {
      stopLiveAudio(true);
      return;
    }
    if (startingRef.current) return;
    if (!realtimeReady) {
      setMicState(realtimeUnavailableReason || "实时语音未启用");
      return;
    }
    if (muted) {
      setMicState("静音中");
      return;
    }
    startingRef.current = true;
    const stream = streamRef.current ?? (await startMic());
    if (!stream) {
      startingRef.current = false;
      return;
    }

    audioSentRef.current = false;
    if (voiceSettings.vadProvider === "ten") try {
      const tenRecorder = new TenVadRecorder({
        threshold: voiceSettings.tenThreshold,
        rmsFloor: voiceSettings.tenRmsFloor,
        debounceOn: voiceSettings.tenDebounceOn,
        debounceOff: voiceSettings.tenDebounceOff,
        preRollMs: voiceSettings.preRollMs,
        initialSilenceMs: voiceSettings.initialSilenceMs,
        maxTurnMs: voiceSettings.maxTurnMs,
        minSpeechMs: voiceSettings.minSpeechMs,
        inputGain: voiceSettings.inputGain,
        streamChunks: voiceSettings.sendMode === "streaming_chunks",
        onSpeechStart: () => {
          traceIdRef.current = createId("turn");
          setSpeechInputActive(true, "speech_start");
          setMicState("TEN VAD: 检测到语音");
          console.warn(`MODVII mic TEN VAD speech start ${JSON.stringify({
            traceId: traceIdRef.current,
            sendMode: voiceSettings.sendMode,
            route: voiceSettings.route,
          })}`);
        },
        onSpeechChunk: (pcm) => {
          let sentChunks = 0;
          for (const chunk of splitPcm16Buffer(pcm)) {
            const sent = sendAudioChunk(chunk, false, { source: "ten_vad_stream" });
            if (!sent) {
              setSpeechInputActive(false, "error");
              setMicState("WebSocket 未连接");
              return;
            }
            sentChunks += 1;
            audioSentRef.current = true;
          }
          if (sentChunks > 0) setMicState("TEN VAD: streaming");
        },
        onSpeechEnd: (pcm, stats) => {
          if (!tenVadRecorderRef.current) return;
          const result =
            voiceSettings.sendMode === "streaming_chunks" && audioSentRef.current
              ? {
                  sentAudio: true,
                  sentFinal: sendAudioChunk(new ArrayBuffer(0), true, {
                    source: "ten_vad_stream",
                    vad_stats: stats,
                  }),
                  sentChunks: 0,
                  totalBytes: pcm.byteLength,
                }
              : sendAudioTurn(pcm);
          audioSentRef.current = audioSentRef.current || result.sentAudio;
          console.warn(`MODVII mic TEN VAD speech end ${JSON.stringify({
            traceId: traceIdRef.current,
            sendMode: voiceSettings.sendMode,
            route: voiceSettings.route,
            ...stats,
            ...result,
          })}`);
          if (!result.sentAudio || !result.sentFinal) {
            setMicState("WebSocket 未连接");
          } else {
            setMicState("正在回应");
          }
          window.setTimeout(() => stopLiveAudio(false), 0);
        },
        onVADMisfire: (stats) => {
          setSpeechInputActive(false, "cancel");
          setMicState("等待语音");
          console.warn(`MODVII mic TEN VAD misfire ${JSON.stringify(stats)}`);
        },
        onNoSpeechTimeout: () => {
          setSpeechInputActive(false, "cancel");
          stopLiveAudio(false);
          setMicState("未检测到语音");
        },
        onError: (error) => {
          setSpeechInputActive(false, "error");
          setMicState(error.message);
          console.warn("MODVII mic TEN VAD error", error);
        },
        onDebug: (message, detail) => {
          console.warn(message, detail ?? "");
        },
      });
      tenVadRecorderRef.current = tenRecorder;
      await tenRecorder.start(stream);
      setLiveStreaming(true);
      setMicState("TEN VAD: 等待语音");
      console.warn("MODVII mic TEN VAD started");
      return;
    } catch (error) {
      tenVadRecorderRef.current?.stop();
      tenVadRecorderRef.current = null;
      console.warn("MODVII mic TEN VAD unavailable; falling back to Silero", error);
    }

    if (voiceSettings.vadProvider !== "rms") try {
      const vad = await MicVAD.new({
        model: "v5",
        baseAssetPath: publicAssetBase("vendor/vad/"),
        onnxWASMBasePath: publicAssetBase("vendor/onnxruntime/"),
        startOnLoad: false,
        processorType: "ScriptProcessor",
        positiveSpeechThreshold: voiceSettings.sileroPositiveThreshold,
        negativeSpeechThreshold: voiceSettings.sileroNegativeThreshold,
        redemptionMs: voiceSettings.silenceAfterSpeechMs,
        preSpeechPadMs: voiceSettings.preRollMs,
        minSpeechMs: voiceSettings.minSpeechMs,
        submitUserSpeechOnPause: true,
        getStream: async () => stream,
        pauseStream: async () => undefined,
        resumeStream: async () => stream,
        onSpeechStart: () => {
          setSpeechInputActive(true, "speech_start");
          setMicState("检测到语音");
          console.warn("MODVII mic Silero speech start");
        },
        onSpeechRealStart: () => {
          setSpeechInputActive(true, "speech_start");
          setMicState("live streaming");
        },
        onSpeechEnd: (audio) => {
          if (!sileroVadRef.current) return;
          const pcm = scalePcm16Buffer(encodePcm16(audio), voiceSettings.inputGain);
          const result = pcm.byteLength > 0
            ? sendAudioTurn(pcm)
            : { sentAudio: false, sentFinal: false, sentChunks: 0, totalBytes: 0 };
          audioSentRef.current = audioSentRef.current || result.sentAudio;
          console.warn(`MODVII mic Silero speech end ${JSON.stringify({
            samples: audio.length,
            ...result,
          })}`);
          if (!result.sentAudio || !result.sentFinal) {
            setMicState("WebSocket 未连接");
          } else {
            setMicState("正在回应");
          }
          window.setTimeout(() => stopLiveAudio(false), 0);
        },
        onVADMisfire: () => {
          setSpeechInputActive(false, "cancel");
          setMicState("等待语音");
          console.warn("MODVII mic Silero VAD misfire");
        },
        onFrameProcessed: () => undefined,
      });
      sileroVadRef.current = vad;
      await vad.start();
      setLiveStreaming(true);
      setMicState("等待语音");
      console.warn("MODVII mic Silero started");
      return;
    } catch (error) {
      const vad = sileroVadRef.current;
      sileroVadRef.current = null;
      void vad?.destroy().catch(() => undefined);
      console.warn("MODVII mic Silero unavailable; falling back to RMS gate", error);
    }

    audioGateRef.current = new LiveAudioGate({
      sampleRate: LIVE_INPUT_SAMPLE_RATE,
      startThreshold: Math.max(0.002, voiceSettings.tenRmsFloor),
      continueThreshold: Math.max(0.0015, voiceSettings.tenRmsFloor * 0.6),
      minContinueThreshold: 0.0015,
      noiseMargin: 0.0025,
      peakDropRatio: 0.2,
      initialSilenceMs: voiceSettings.initialSilenceMs,
      silenceAfterSpeechMs: voiceSettings.silenceAfterSpeechMs,
      maxTurnMs: voiceSettings.maxTurnMs,
    });
    audioSentRef.current = false;
    const recorder = new PcmRecorder({
      outputSampleRate: LIVE_INPUT_SAMPLE_RATE,
      inputGain: voiceSettings.inputGain,
      onChunk: (chunk) => {
        const gate = audioGateRef.current;
        const decision: LiveAudioGateDecision = gate
          ? gate.accept(chunk)
          : { chunks: [chunk], rms: 0, state: "speaking", shouldStop: false, sendFinal: false };

        let sent = true;
        for (const gatedChunk of decision.chunks) {
          sent = sendAudioChunk(gatedChunk, false);
          if (!sent) break;
          audioSentRef.current = true;
        }

        if (!sent) {
          stopLiveAudio(false);
          setMicState("WebSocket 未连接");
          return;
        }

        if (decision.state === "waiting") {
          setMicState("等待语音");
        } else if (decision.state === "speaking") {
          setMicState("live streaming");
        } else if (decision.state === "silence") {
          setMicState("检测静音");
        }

        if (decision.shouldStop) {
          console.warn("MODVII mic RMS gate stop", {
            rms: decision.rms,
            sendFinal: decision.sendFinal,
            state: decision.state,
          });
          if (decision.state === "initial_timeout") {
            stopLiveAudio(false);
            setMicState("未检测到语音");
          } else if (decision.state === "max_turn") {
            stopLiveAudio(decision.sendFinal);
            setMicState("单轮已达上限");
          } else {
            stopLiveAudio(decision.sendFinal);
          }
        }
      },
      onError: (error) => {
        setSpeechInputActive(false, "error");
        setMicState(error.message);
      },
    });
    recorderRef.current = recorder;
    try {
      await recorder.start(stream);
      setLiveStreaming(true);
      setMicState("live streaming");
    } catch (error) {
      recorderRef.current = null;
      setMicState(error instanceof Error ? error.message : "实时语音不可用");
    } finally {
      startingRef.current = false;
    }
  }
  startLiveAudioRef.current = startLiveAudio;

  useEffect(() => {
    onLiveStateChange?.(liveStreaming);
  }, [liveStreaming, onLiveStateChange]);

  function startWakeRecognition() {
    recognitionWantedRef.current = true;
    if (recognitionRef.current || recognitionActive) return;
    if (muted) {
      setMicState("静音中，无法监听唤醒词");
      return;
    }
    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setMicState(realtimeReady ? "无本地关键词识别，改用直接语音监听" : "浏览器不支持 SpeechRecognition");
      if (realtimeReady) {
        void startLiveAudio();
      }
      return;
    }
    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      const changedTranscript = Array.from(event.results)
        .slice(event.resultIndex)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      const fullTranscript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      const now = Date.now();
      const candidate = [changedTranscript, fullTranscript]
        .map((value) => value.trim())
        .find((value) => extractWakeRequest(value, wakeWord).matched);
      if (!candidate) return;

      const wakeRequest = extractWakeRequest(candidate, wakeWord);
      const requestText = wakeRequest.requestText.trim();
      const dedupeKey = `${candidate}|${requestText}`;
      if (dedupeKey === handledWakeTranscriptRef.current) return;
      if (!wakePendingRef.current && now - wakeAtRef.current < 1200) return;

      if (!wakePendingRef.current) {
        wakeAtRef.current = now;
        const wakeSent = onWake();
        if (wakeSent === false) {
          setMicState("WebSocket 未连接，唤醒未发送");
          return;
        }
        wakePendingRef.current = true;
      }

      if (requestText) {
        pendingWakeRequestRef.current = requestText;
      }
      window.clearTimeout(pendingWakeTimerRef.current);
      pendingWakeTimerRef.current = window.setTimeout(() => {
        const finalRequest = pendingWakeRequestRef.current.trim();
        handledWakeTranscriptRef.current = `${candidate}|${finalRequest}`;
        wakePendingRef.current = false;
        pendingWakeTimerRef.current = 0;
        pendingWakeRequestRef.current = "";
        stopWakeRecognition();
        if (finalRequest) {
          stopLiveAudio(false);
          onUserText(finalRequest, { keepConversation: true });
          return;
        }
        void startLiveAudio();
      }, requestText ? 420 : 650);
    };
    recognition.onerror = (event) => {
      const reason = (event as Event & { error?: string }).error ?? "unknown";
      const terminalError = ["network", "not-allowed", "service-not-allowed", "language-not-supported"].includes(
        reason,
      );
      if (terminalError) {
        recognitionWantedRef.current = false;
        setMicState(realtimeReady ? `关键词监听失败：${reason}，改用实时语音` : `关键词监听暂不可用：${reason}`);
        if (realtimeReady && !muted) {
          window.setTimeout(() => {
            void startLiveAudio();
          }, 250);
        }
        return;
      }
      setMicState(`关键词监听暂不可用：${reason}`);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setRecognitionActive(false);
      if (recognitionWantedRef.current && !muted) {
        recognitionRestartTimerRef.current = window.setTimeout(() => startWakeRecognition(), 450);
        return;
      }
      setMicState("ready");
    };
    try {
      recognition.start();
    } catch {
      setMicState("语音识别已经在运行");
      return;
    }
    recognitionRef.current = recognition;
    setRecognitionActive(true);
    setMicState(`监听唤醒词：${wakeWord}`);
  }

  function toggleWakeRecognition() {
    if (recognitionActive || recognitionRef.current) {
      stopWakeRecognition();
      setMicState("ready");
      return;
    }
    startWakeRecognition();
  }
  startWakeRecognitionRef.current = startWakeRecognition;

  function submitText() {
    const trimmed = text.trim();
    if (!trimmed) return;
    const wakeRequest = extractWakeRequest(trimmed, wakeWord);
    if (wakeRequest.matched) {
      onWake();
      if (wakeRequest.requestText) {
        onUserText(wakeRequest.requestText, { keepConversation: true });
      } else {
        void startLiveAudio();
      }
    } else {
      onUserText(trimmed);
    }
    setText("");
  }

  useEffect(() => {
    return () => {
      stopWakeRecognition();
      stopMic();
    };
  }, [stopMic]);

  useEffect(() => {
    if (autoStartSignal > 0) {
      void startMic();
    }
  }, [autoStartSignal, startMic]);

  useEffect(() => {
    if (wakeListenSignal > 0) {
      recognitionWantedRef.current = false;
      void startLiveAudioRef.current();
    }
  }, [wakeListenSignal]);

  useEffect(() => {
    if (keywordListenSignal > 0) {
      void startMic().finally(() => startWakeRecognitionRef.current());
    }
  }, [keywordListenSignal, startMic]);

  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
    if (muted) {
      stopWakeRecognition();
      stopLiveAudio(true);
    }
  }, [muted, stopLiveAudio]);

  useEffect(() => {
    if (stopSignal > 0) {
      stopWakeRecognition();
      stopLiveAudio(false);
    }
  }, [stopSignal, stopLiveAudio]);

  useEffect(() => {
    if (liveStreaming && !realtimeReady) {
      stopLiveAudio(false);
      setMicState(realtimeUnavailableReason || "实时语音未启用");
    }
  }, [liveStreaming, realtimeReady, realtimeUnavailableReason, stopLiveAudio]);

  return (
    <section className="panel mic-panel">
      <div className="panel-title">
        <Mic size={18} />
        <span>Mic</span>
      </div>
      <div className="level-meter" aria-label="输入音量">
        <span style={{ transform: `scaleX(${muted ? 0 : level})` }} />
      </div>
      <div className="toolbar">
        <button className="icon-button" type="button" title="授权麦克风" onClick={() => void startMic()}>
          <Mic size={18} />
        </button>
        <button className="icon-button" type="button" title="切换静音" onClick={() => setMuted((value) => !value)}>
          {muted ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
        <button
          className={`icon-button${recognitionActive ? " active" : ""}`}
          type="button"
          title={recognitionActive ? "停止关键词监听" : "监听唤醒词"}
          onClick={toggleWakeRecognition}
        >
          <Radio size={18} />
        </button>
        <button
          className={`icon-button${liveStreaming ? " active" : ""}`}
          type="button"
          title={liveButtonTitle}
          disabled={!liveStreaming && !realtimeReady}
          onClick={() => void startLiveAudio()}
        >
          {liveStreaming ? <Square size={17} /> : <AudioLines size={18} />}
        </button>
      </div>
      <div className="input-row">
        <input
          value={text}
          placeholder={`输入“${wakeWord}”唤醒，或输入问题`}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) submitText();
          }}
        />
        <button className="icon-button" type="button" title="发送文本" onClick={submitText}>
          <Send size={18} />
        </button>
      </div>
      <dl className="metric-list">
        <div>
          <dt>状态</dt>
          <dd>{recognitionActive ? `${micState} / active` : micState}</dd>
        </div>
        <div>
          <dt>会话</dt>
          <dd>{sessionId ? "ready" : "pending"}</dd>
        </div>
        <div>
          <dt>实时</dt>
          <dd>
            {liveStreaming
              ? "streaming"
              : realtimeAvailable
                ? realtimeFormatCompatible
                  ? "off"
                  : "incompatible"
                : "unavailable"}
          </dd>
        </div>
        <div>
          <dt>输入优化</dt>
          <dd>降噪/回声消除/自动增益</dd>
        </div>
        {!liveStreaming && realtimeUnavailableReason ? (
          <div>
            <dt>按钮原因</dt>
            <dd>{realtimeUnavailableReason}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
