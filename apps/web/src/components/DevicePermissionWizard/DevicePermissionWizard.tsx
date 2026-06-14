import { CheckCircle2, Mic, MonitorUp, Power, Video } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { requestScreenCapture, stopMediaStream } from "../../features/media/screenCapture";
import { getDesktopSettings, isDesktopRuntime, setDesktopSettings } from "../../lib/desktopBridge";

interface PermissionWizardProps {
  onComplete: () => void;
}

interface PermissionStatus {
  mic: string;
  camera: string;
  screen: string;
  autostart: string;
}

const initialStatus: PermissionStatus = {
  mic: "pending",
  camera: "pending",
  screen: "pending",
  autostart: "pending",
};

const permissionStatusLabel: Record<string, string> = {
  pending: "等待",
  ready: "已授权",
  failed: "失败",
  enabled: "已启用",
  disabled: "未启用",
};

export function DevicePermissionWizard({ onComplete }: PermissionWizardProps) {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [autostart, setAutostart] = useState(false);
  const [status, setStatus] = useState<PermissionStatus>(initialStatus);

  useEffect(() => {
    async function load() {
      const settings = await getDesktopSettings();
      if (settings.firstRunComplete) {
        onComplete();
        return;
      }
      setAutostart(Boolean(settings.autostartEnabled));
      setVisible(isDesktopRuntime());
    }
    void load();
  }, [onComplete]);

  if (!visible) return null;

  async function requestAll() {
    setBusy(true);
    const next: PermissionStatus = { ...initialStatus };
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
        video: false,
      });
      stopMediaStream(micStream);
      next.mic = "ready";
    } catch (error) {
      next.mic = error instanceof Error ? error.message : "failed";
    }
    setStatus({ ...next });

    try {
      const cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      stopMediaStream(cameraStream);
      next.camera = "ready";
    } catch (error) {
      next.camera = error instanceof Error ? error.message : "failed";
    }
    setStatus({ ...next });

    try {
      const screen = await requestScreenCapture();
      stopMediaStream(screen.stream);
      next.screen = "ready";
    } catch (error) {
      next.screen = error instanceof Error ? error.message : "failed";
    }
    setStatus({ ...next });

    try {
      if (window.modvii) {
        await window.modvii.autostart.set(autostart);
      }
      next.autostart = autostart ? "enabled" : "disabled";
    } catch (error) {
      next.autostart = error instanceof Error ? error.message : "failed";
    }
    setStatus({ ...next });

    await setDesktopSettings({
      firstRunComplete: true,
      autostartAsked: true,
      autostartEnabled: autostart,
      captureMode: "low_fps",
    });
    setBusy(false);
    setVisible(false);
    onComplete();
  }

  return (
    <section className="panel permission-wizard">
      <div className="panel-title">
        <CheckCircle2 size={18} />
        <span>MODVII 首次授权</span>
      </div>
      <div className="permission-grid">
        <PermissionItem icon={<Mic size={16} />} label="麦克风" value={status.mic} />
        <PermissionItem icon={<Video size={16} />} label="摄像头" value={status.camera} />
        <PermissionItem icon={<MonitorUp size={16} />} label="屏幕" value={status.screen} />
        <PermissionItem icon={<Power size={16} />} label="开机自启" value={status.autostart} />
      </div>
      <label className="check-row permission-autostart">
        <input type="checkbox" checked={autostart} onChange={(event) => setAutostart(event.target.checked)} />
        开机后自动启动 MODVII
      </label>
      <button className="tool-button" type="button" disabled={busy} onClick={() => void requestAll()}>
        <CheckCircle2 size={18} />
        {busy ? "授权中" : "授权并启动 MODVII"}
      </button>
    </section>
  );
}

function PermissionItem({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="permission-item">
      <span>
        {icon}
        {label}
      </span>
      <strong>{permissionStatusLabel[value] ?? value}</strong>
    </div>
  );
}
