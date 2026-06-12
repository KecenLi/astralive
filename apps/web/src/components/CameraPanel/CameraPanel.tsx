import { Camera, RefreshCw, ScanEye, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import { createEvent, FramePayload } from "../../lib/events";
import { wsClient } from "../../lib/wsClient";
import { captureVideoFrame } from "../../features/media/frameCapture";
import { createMockFrame } from "../../features/media/mockFrame";

interface CameraPanelProps {
  onFrameSent: (frame: FramePayload) => void;
}

export function CameraPanel({ onFrameSent }: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [cameraState, setCameraState] = useState("未授权");
  const sessionId = useAppStore((state) => state.sessionId);
  const wakeSerial = useAppStore((state) => state.wakeSerial);
  const lastFrameInfo = useAppStore((state) => state.lastFrameInfo);

  async function startCamera(nextDeviceId = deviceId) {
    try {
      streamRef.current?.getTracks().forEach((track) => track.stop());
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
  }

  const sendFrame = useCallback(async (reason: FramePayload["capture_reason"], prompt: string) => {
    let frame: FramePayload;
    if (videoRef.current?.videoWidth) {
      frame = await captureVideoFrame(videoRef.current, reason, prompt, {
        quality: reason === "focus_roi" ? 0.9 : 0.72,
        maxWidth: reason === "focus_roi" ? 1600 : 1280,
        maxHeight: reason === "focus_roi" ? 900 : 720,
      });
    } else {
      frame = createMockFrame(reason, prompt);
    }
    onFrameSent(frame);
    if (sessionId) {
      wsClient.send(createEvent("client.media.frame", sessionId, frame));
    }
  }, [onFrameSent, sessionId]);

  useEffect(() => {
    if (wakeSerial > 0) {
      void sendFrame("wake_snapshot", "唤醒时生成低成本视觉摘要。");
    }
  }, [sendFrame, wakeSerial]);

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
          title="普通视觉上传"
          onClick={() => void sendFrame("visual_question", "用户问了视觉相关问题。")}
        >
          <Upload size={18} />
        </button>
        <button
          className="icon-button"
          type="button"
          title="高清凝视"
          onClick={() => void sendFrame("focus_roi", "用户要求看清楚一点或读文字。")}
        >
          <ScanEye size={18} />
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
