import { Camera, RefreshCw, ScanEye, Upload, Video } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import { captureVideoFrame } from "../../features/media/frameCapture";
import {
  activityFromStatus,
  captureOptionsFor,
  captureReasonFor,
  getFrameIntervalMs,
  sceneHashDistance,
  shouldSendSceneHash,
  VisualCaptureActivity,
  VisualCaptureMode,
} from "../../features/media/frameSampler";
import { createMockFrame } from "../../features/media/mockFrame";
import { createEvent, FramePayload, VisualFrameMetricPayload } from "../../lib/events";
import { wsClient } from "../../lib/wsClient";

interface CameraPanelProps {
  autoStartSignal: number;
  onFrameSent: (frame: FramePayload) => void;
  suspendAutoUpload?: boolean;
}

export function CameraPanel({ autoStartSignal, onFrameSent, suspendAutoUpload = false }: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastSceneHashRef = useRef<string | null>(null);
  const captureInFlightRef = useRef(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [cameraState, setCameraState] = useState("未授权");
  const [mode, setMode] = useState<VisualCaptureMode>("low_fps");
  const [autoUpload, setAutoUpload] = useState(true);
  const [focusUntil, setFocusUntil] = useState(0);
  const sessionId = useAppStore((state) => state.sessionId);
  const status = useAppStore((state) => state.status);
  const lastFrameInfo = useAppStore((state) => state.lastFrameInfo);
  const sceneChangeThreshold = useAppStore((state) => state.visualCapabilities.scene_change_threshold);

  const sendVisualMetric = useCallback(
    (payload: Omit<VisualFrameMetricPayload, "source">) => {
      if (!sessionId) return;
      wsClient.send(createEvent("client.metrics.visual_frame", sessionId, { source: "camera", ...payload }));
    },
    [sessionId],
  );

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    lastSceneHashRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const startCamera = useCallback(async (nextDeviceId = deviceId) => {
    try {
      stopCamera();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: nextDeviceId ? { deviceId: { exact: nextDeviceId } } : true,
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setCameraState("ready");
      const allDevices = await navigator.mediaDevices.enumerateDevices();
      setDevices(allDevices.filter((device) => device.kind === "videoinput"));
    } catch (error) {
      setCameraState(error instanceof Error ? error.message : "摄像头不可用");
    }
  }, [deviceId, stopCamera]);

  const sendFrame = useCallback(
    async (reason: FramePayload["capture_reason"], prompt: string, activity: VisualCaptureActivity = "active") => {
      if (captureInFlightRef.current) return;
      const video = videoRef.current;
      if (!video?.videoWidth) {
        setCameraState("摄像头未就绪，未上传真实画面");
        return;
      }
      captureInFlightRef.current = true;
      try {
        const frame = await captureVideoFrame(video, reason, prompt, captureOptionsFor(mode, activity));
        const hashDistance = sceneHashDistance(lastSceneHashRef.current, frame.scene_hash);
        sendVisualMetric({
          event: "candidate",
          capture_reason: reason,
          frame_id: frame.frame_id,
          ...(hashDistance === null ? {} : { scene_hash_distance: hashDistance }),
        });
        if (
          !shouldSendSceneHash(
            lastSceneHashRef.current,
            frame.scene_hash,
            activity,
            sceneChangeThreshold,
          )
        ) {
          sendVisualMetric({
            event: "client_deduped",
            capture_reason: reason,
            frame_id: frame.frame_id,
            ...(hashDistance === null ? {} : { scene_hash_distance: hashDistance }),
          });
          setCameraState("重复画面跳过");
          return;
        }
        lastSceneHashRef.current = frame.scene_hash;
        onFrameSent(frame);
        if (sessionId) {
          const sent = wsClient.send(createEvent("client.media.frame", sessionId, frame));
          setCameraState(sent ? `sent ${reason}` : "WebSocket 未连接，帧未发送");
        } else {
          setCameraState("会话未就绪，帧未发送");
        }
      } finally {
        captureInFlightRef.current = false;
      }
    },
    [mode, onFrameSent, sceneChangeThreshold, sendVisualMetric, sessionId],
  );

  const sendMockFrame = useCallback(() => {
    const frame = createMockFrame("manual_debug", "手动 Mock 帧，仅用于无摄像头演示。");
    onFrameSent(frame);
    if (sessionId) {
      const sent = wsClient.send(createEvent("client.media.frame", sessionId, frame));
      if (!sent) setCameraState("WebSocket 未连接，Mock 帧未发送");
    }
  }, [onFrameSent, sessionId]);

  useEffect(() => {
    if (autoStartSignal > 0) {
      void startCamera();
    }
  }, [autoStartSignal, startCamera]);

  useEffect(() => stopCamera, [stopCamera]);

  useEffect(() => {
    if (suspendAutoUpload && autoUpload) {
      setCameraState("语音优先，暂停自动上传");
    }
  }, [autoUpload, suspendAutoUpload]);

  useEffect(() => {
    if (!autoUpload || !streamRef.current) return;
    let disposed = false;
    let timer = 0;

    async function tick() {
      const activity: VisualCaptureActivity =
        Date.now() < focusUntil ? "focus" : activityFromStatus(status);
      const reason = captureReasonFor("camera", mode, activity);
      if (suspendAutoUpload || status === "sleeping") {
        sendVisualMetric({ event: "sleep_blocked", capture_reason: reason });
        setCameraState(status === "sleeping" ? "睡眠中，自动采样拦截" : "语音优先，暂停自动上传");
        if (!disposed) {
          timer = window.setTimeout(tick, getFrameIntervalMs(mode, activity));
        }
        return;
      }
      await sendFrame(reason, "连续摄像头视觉上下文。", activity);
      if (!disposed) {
        timer = window.setTimeout(tick, getFrameIntervalMs(mode, activity));
      }
    }

    timer = window.setTimeout(tick, 800);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [autoUpload, focusUntil, mode, sendFrame, sendVisualMetric, status, suspendAutoUpload]);

  return (
    <section className="panel camera-panel">
      <div className="panel-title">
        <Camera size={18} />
        <span>Camera</span>
      </div>
      <video ref={videoRef} className="camera-preview" autoPlay muted playsInline />
      <div className="toolbar">
        <button className="icon-button" type="button" title="启动摄像头" onClick={() => void startCamera()}>
          <Camera size={18} />
        </button>
        <button
          className="icon-button"
          type="button"
          title="上传摄像头帧"
          onClick={() => void sendFrame("visual_question", "用户问了视觉相关问题。", "active")}
        >
          <Upload size={18} />
        </button>
        <button
          className="icon-button"
          type="button"
          title="高清凝视"
          onClick={() => {
            setFocusUntil(Date.now() + 10_000);
            void sendFrame("focus_roi", "用户要求看清楚一点或读文字。", "focus");
          }}
        >
          <ScanEye size={18} />
        </button>
        <button
          className="icon-button"
          type="button"
          title="手动 Mock 帧"
          onClick={sendMockFrame}
        >
          <Upload size={18} />
        </button>
        <button
          className="icon-button"
          type="button"
          title="重启摄像头"
          onClick={() => void startCamera(deviceId)}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <select
        className="select"
        value={deviceId}
        onChange={(event) => {
          setDeviceId(event.target.value);
          void startCamera(event.target.value);
        }}
      >
        <option value="">默认摄像头</option>
        {devices.map((device, index) => (
          <option key={device.deviceId} value={device.deviceId}>
            {device.label || `摄像头 ${index + 1}`}
          </option>
        ))}
      </select>
      <div className="capture-controls">
        <label>
          <Video size={15} />
          <select
            className="select inline-select"
            value={mode}
            onChange={(event) => setMode(event.target.value as VisualCaptureMode)}
          >
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
          <dd>{cameraState}</dd>
        </div>
        <div>
          <dt>最近帧</dt>
          <dd>{lastFrameInfo}</dd>
        </div>
      </dl>
    </section>
  );
}
