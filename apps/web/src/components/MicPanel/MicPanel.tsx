import { AudioLines, Mic, MicOff, Radio, Send, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import {
  arrayBufferToBase64,
  LIVE_INPUT_SAMPLE_RATE,
  PcmRecorder,
} from "../../features/media/pcmRecorder";
import { LiveAudioGate, LiveAudioGateDecision } from "../../features/media/voiceActivity";
import { getSpeechRecognition, SpeechRecognition } from "../../features/wakeword/speechRecognition";
import { AudioChunkPayload, createId } from "../../lib/events";

interface MicPanelProps {
  onWake: () => void;
  onUserText: (text: string) => void;
  onAudioChunk: (payload: AudioChunkPayload) => boolean;
  stopSignal: number;
}

export function MicPanel({ onWake, onUserText, onAudioChunk, stopSignal }: MicPanelProps) {
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
  const audioSentRef = useRef(false);
  const startingRef = useRef(false);
  const rafRef = useRef(0);
  const wakeAtRef = useRef(0);
  const [recognitionActive, setRecognitionActive] = useState(false);
  const sessionId = useAppStore((state) => state.sessionId);
  const connection = useAppStore((state) => state.connection);
  const wakeWord = useAppStore((state) => state.wakeWord);
  const audioCapabilities = useAppStore((state) => state.audioCapabilities);
  const realtimeAvailable = Boolean(audioCapabilities?.server_realtime_audio);
  const realtimeReady = Boolean(sessionId) && connection === "connected" && realtimeAvailable;
  const liveButtonTitle = liveStreaming
    ? "结束实时语音"
    : realtimeAvailable
      ? "开始实时语音"
      : "实时语音未启用";

  function stopMic() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    audioGateRef.current = null;
    audioSentRef.current = false;
    setLiveStreaming(false);
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setLevel(0);
  }

  async function startMic() {
    try {
      stopMic();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
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
  }

  const sendAudioChunk = useCallback((buffer: ArrayBuffer, isFinal: boolean) => {
    if (!sessionId) return false;
    const payload: AudioChunkPayload = {
      chunk_id: createId("aud"),
      mime: `audio/pcm;rate=${LIVE_INPUT_SAMPLE_RATE}`,
      sample_rate: LIVE_INPUT_SAMPLE_RATE,
      channels: 1,
      encoding: "pcm_s16le",
      data_base64: buffer.byteLength > 0 ? arrayBufferToBase64(buffer) : "",
      is_final: isFinal,
      metadata: { source: "browser_pcm" },
    };
    return onAudioChunk(payload);
  }, [onAudioChunk, sessionId]);

  const stopLiveAudio = useCallback(
    (sendFinal: boolean) => {
      const hadRecorder = Boolean(recorderRef.current);
      recorderRef.current?.stop();
      recorderRef.current = null;
      audioGateRef.current?.reset();
      audioGateRef.current = null;
      startingRef.current = false;
      setLiveStreaming(false);
      const shouldSendFinal = sendFinal && hadRecorder && audioSentRef.current;
      if (shouldSendFinal) {
        const sent = sendAudioChunk(new ArrayBuffer(0), true);
        if (!sent) setMicState("WebSocket 未连接");
      }
      audioSentRef.current = false;
      if (hadRecorder) {
        setMicState("ready");
      }
    },
    [sendAudioChunk],
  );

  async function startLiveAudio() {
    if (liveStreaming || recorderRef.current) {
      stopLiveAudio(true);
      return;
    }
    if (startingRef.current) return;
    if (!realtimeReady) {
      setMicState(connection === "connected" ? "实时语音未启用" : "WebSocket 未连接");
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

    audioGateRef.current = new LiveAudioGate({ sampleRate: LIVE_INPUT_SAMPLE_RATE });
    audioSentRef.current = false;
    const recorder = new PcmRecorder({
      outputSampleRate: LIVE_INPUT_SAMPLE_RATE,
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
      onError: (error) => setMicState(error.message),
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

  function startWakeRecognition() {
    if (recognitionActive) return;
    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setMicState("浏览器不支持 SpeechRecognition，可用文本模拟");
      return;
    }
    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .slice(event.resultIndex)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      const now = Date.now();
      if (transcript.includes(wakeWord) && now - wakeAtRef.current > 4000) {
        wakeAtRef.current = now;
        onWake();
      }
    };
    recognition.onerror = () => setMicState("语音识别暂不可用");
    recognition.onend = () => {
      setRecognitionActive(false);
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
    setMicState("wake listening");
  }

  function submitText() {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (trimmed.includes(wakeWord)) {
      onWake();
    } else {
      onUserText(trimmed);
    }
    setText("");
  }

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      stopMic();
    };
  }, []);

  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
    if (muted) {
      recognitionRef.current?.stop();
      stopLiveAudio(true);
    }
  }, [muted, stopLiveAudio]);

  useEffect(() => {
    if (stopSignal > 0) {
      recognitionRef.current?.stop();
      stopLiveAudio(false);
    }
  }, [stopSignal, stopLiveAudio]);

  useEffect(() => {
    if (liveStreaming && !realtimeReady) {
      stopLiveAudio(false);
      setMicState(connection === "connected" ? "实时语音未启用" : "WebSocket 未连接");
    }
  }, [connection, liveStreaming, realtimeReady, stopLiveAudio]);

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
        <button className="icon-button" type="button" title="监听唤醒词" onClick={startWakeRecognition}>
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
          <dd>{liveStreaming ? "streaming" : realtimeAvailable ? "off" : "unavailable"}</dd>
        </div>
      </dl>
    </section>
  );
}
