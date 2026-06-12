import { Mic, MicOff, Radio, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import { getSpeechRecognition, SpeechRecognition } from "../../features/wakeword/speechRecognition";

interface MicPanelProps {
  onWake: () => void;
  onUserText: (text: string) => void;
}

export function MicPanel({ onWake, onUserText }: MicPanelProps) {
  const [micState, setMicState] = useState("未授权");
  const [muted, setMuted] = useState(false);
  const [level, setLevel] = useState(0);
  const [text, setText] = useState("");
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const rafRef = useRef(0);
  const sessionId = useAppStore((state) => state.sessionId);
  const wakeWord = useAppStore((state) => state.wakeWord);

  async function startMic() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const audioContext = new AudioContext();
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
    } catch (error) {
      setMicState(error instanceof Error ? error.message : "麦克风不可用");
    }
  }

  function startWakeRecognition() {
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
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      if (transcript.includes(wakeWord)) {
        onWake();
      }
    };
    recognition.onerror = () => setMicState("语音识别暂不可用");
    recognition.start();
    recognitionRef.current = recognition;
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
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

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
      </div>
      <div className="input-row">
        <input
          value={text}
          placeholder={`输入“${wakeWord}”唤醒，或输入问题`}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitText();
          }}
        />
        <button className="icon-button" type="button" title="发送文本" onClick={submitText}>
          <Send size={18} />
        </button>
      </div>
      <dl className="metric-list">
        <div>
          <dt>状态</dt>
          <dd>{micState}</dd>
        </div>
        <div>
          <dt>会话</dt>
          <dd>{sessionId ? "ready" : "pending"}</dd>
        </div>
      </dl>
    </section>
  );
}
