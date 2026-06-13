import { RefreshCw, ScanEye, ScreenShare, Square, Upload, Video } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import { captureVideoFrame } from "../../features/media/frameCapture";
import {
  activityFromStatus,
  captureOptionsFor,
  captureReasonFor,
  getFrameIntervalMs,
  shouldSendSceneHash,
  VisualCaptureActivity,
  VisualCaptureMode,
} from "../../features/media/frameSampler";
import { requestScreenCapture, stopMediaStream } from "../../features/media/screenCapture";
import { createEvent, FramePayload } from "../../lib/events";
import { wsClient } from "../../lib/wsClient";

interface ScreenCapturePanelProps {
  autoStartSignal: number;
  onFrameSent: (frame: FramePayload) => void;
  suspendAutoUpload?: boolean;
}

export function ScreenCapturePanel({ autoStartSignal, onFrameSent, suspendAutoUpload = false }: ScreenCapturePanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastSceneHashRef = useRef<string | null>(null);
  const captureInFlightRef = useRef(false);
  const [captureState, setCaptureState] = useState("未授权");
  const [sourceName, setSourceName] = useState("未选择");
  const [mode, setMode] = useState<VisualCaptureMode>("low_fps");
  const [autoUpload, setAutoUpload] = useState(true);
  const [focusUntil, setFocusUntil] = useState(0);
  const [lastFrameInfo, setLastFrameInfo] = useState("尚未上传");
  const sessionId = useAppStore((state) => state.sessionId);
  const status = useAppStore((state) => state.status);

  const stopScreen = useCallback(() => {
    stopMediaStream(streamRef.current);
    streamRef.current = null;
    lastSceneHashRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCaptureState("stopped");
  }, []);

  const startScreen = useCallback(async () => {
    try {
      stopScreen();
      const result = await requestScreenCapture();
      streamRef.current = result.stream;
      setSourceName(result.sourceName);
      if (videoRef.current) videoRef.current.srcObject = result.stream;
      result.stream.getVideoTracks()[0]?.addEventListener("ended", () => {
        if (streamRef.current !== result.stream) return;
        setCaptureState("屏幕源已停止");
        streamRef.current = null;
      });
      setCaptureState("ready");
    } catch (error) {
      setCaptureState(error instanceof Error ? error.message : "屏幕捕捉不可用");
    }
  }, [stopScreen]);

  const captureAndSend = useCallback(
    async (activity: VisualCaptureActivity) => {
      if (captureInFlightRef.current) {
        setCaptureState("捕捉仍在进行，跳过本次点击");
        return;
      }
      const video = videoRef.current;
      if (!video?.videoWidth) {
        setCaptureState("屏幕流未就绪");
        return;
      }

      captureInFlightRef.current = true;
      try {
        const reason = captureReasonFor("screen", mode, activity);
        const frame = await captureVideoFrame(
          video,
          reason,
          activity === "focus" ? "用户要求看清楚屏幕内容。" : "连续屏幕视觉上下文。",
          captureOptionsFor(mode, activity),
        );
        if (!shouldSendSceneHash(lastSceneHashRef.current, frame.scene_hash, activity)) {
          setCaptureState("重复画面跳过");
          return;
        }
        lastSceneHashRef.current = frame.scene_hash;
        onFrameSent(frame);
        setLastFrameInfo(`${frame.width}x${frame.height} / ${reason}`);
        if (!sessionId) {
          setCaptureState("会话未就绪，帧未发送");
          return;
        }
        const sent = wsClient.send(createEvent("client.media.frame", sessionId, frame));
        setCaptureState(sent ? `sent ${reason}` : "WebSocket 未连接，帧未发送");
      } catch (error) {
        setCaptureState(error instanceof Error ? error.message : "屏幕帧捕捉失败");
      } finally {
        captureInFlightRef.current = false;
      }
    },
    [mode, onFrameSent, sessionId],
  );

  const focusScreen = useCallback(() => {
    setFocusUntil(Date.now() + 10_000);
    void captureAndSend("focus");
  }, [captureAndSend]);

  useEffect(() => {
    if (autoStartSignal > 0) {
      void startScreen();
    }
  }, [autoStartSignal, startScreen]);

  useEffect(() => stopScreen, [stopScreen]);

  useEffect(() => {
    if (suspendAutoUpload && autoUpload) {
      setCaptureState("语音优先，暂停自动上传");
    }
  }, [autoUpload, suspendAutoUpload]);

  useEffect(() => {
    if (!autoUpload || suspendAutoUpload || !streamRef.current) return;
    let disposed = false;
    let timer = 0;

    async function tick() {
      const activity: VisualCaptureActivity =
        Date.now() < focusUntil ? "focus" : activityFromStatus(status);
      await captureAndSend(activity);
      if (!disposed) {
        timer = window.setTimeout(tick, getFrameIntervalMs(mode, activity));
      }
    }

    timer = window.setTimeout(tick, 600);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [autoUpload, captureAndSend, focusUntil, mode, status, suspendAutoUpload]);

  return (
    <section className="panel screen-panel">
      <div className="panel-title">
        <ScreenShare size={18} />
        <span>Screen</span>
      </div>
      <video ref={videoRef} className="camera-preview" autoPlay muted playsInline />
      <div className="toolbar">
        <button className="icon-button" type="button" title="启动屏幕捕捉" onClick={() => void startScreen()}>
          <ScreenShare size={18} />
        </button>
        <button className="icon-button" type="button" title="停止屏幕捕捉" onClick={stopScreen}>
          <Square size={17} />
        </button>
        <button className="icon-button" type="button" title="上传屏幕帧" onClick={() => void captureAndSend("active")}>
          <Upload size={18} />
        </button>
        <button className="icon-button" type="button" title="高清屏幕凝视" onClick={focusScreen}>
          <ScanEye size={18} />
        </button>
        <button className="icon-button" type="button" title="重启屏幕捕捉" onClick={() => void startScreen()}>
          <RefreshCw size={18} />
        </button>
      </div>
      <div className="capture-controls">
        <label>
          <Video size={15} />
          <select className="select inline-select" value={mode} onChange={(event) => setMode(event.target.value as VisualCaptureMode)}>
            <option value="low_fps">低帧稳定</option>
            <option value="continuous">连续视频采样</option>
          </select>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={autoUpload} onChange={(event) => setAutoUpload(event.target.checked)} />
          自动上传采样帧
        </label>
      </div>
      <dl className="metric-list">
        <div>
          <dt>状态</dt>
          <dd>{captureState}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{sourceName}</dd>
        </div>
        <div>
          <dt>最近帧</dt>
          <dd>{lastFrameInfo}</dd>
        </div>
        <div>
          <dt>节奏</dt>
          <dd>{mode === "low_fps" ? "0.2/1/2 fps" : "0.5/2/5 fps"}</dd>
        </div>
      </dl>
    </section>
  );
}
