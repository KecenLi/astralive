import { PauseCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAppStore } from "../../app/store";
import { describeLive2DError, Live2DAvatarController } from "../../features/avatar/avatarController";
import { LIVE2D_MODEL_URL } from "../../lib/env";

const expressionLabel: Record<string, string> = {
  neutral: "平静",
  happy: "开心",
  curious: "好奇",
  surprised: "惊讶",
  confused: "困惑",
  concerned: "关切",
  thinking: "思考",
  sleepy: "休眠",
};

export function AvatarStage({ onInterrupt }: { onInterrupt: () => void }) {
  const avatar = useAppStore((state) => state.avatar);
  const status = useAppStore((state) => state.status);
  const lipSyncLevel = avatar.lip_sync_level ?? 0;
  const isSpeaking = avatar.mode === "speaking" || avatar.lip_sync || lipSyncLevel > 0.02;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<Live2DAvatarController | null>(null);
  const [isLive2DReady, setIsLive2DReady] = useState(false);

  useEffect(() => {
    if (!LIVE2D_MODEL_URL || !canvasRef.current) return;

    let disposed = false;
    const controller = new Live2DAvatarController();
    controllerRef.current = controller;

    async function mountLive2D() {
      try {
        await controller.mount(canvasRef.current as HTMLCanvasElement, LIVE2D_MODEL_URL);
        if (!disposed) setIsLive2DReady(true);
      } catch (error) {
        console.warn(`Live2D model failed to load; using fallback avatar. ${describeLive2DError(error)}`);
        if (!disposed) setIsLive2DReady(false);
      }
    }

    void mountLive2D();

    return () => {
      disposed = true;
      controller.dispose();
      controllerRef.current = null;
      setIsLive2DReady(false);
    };
  }, []);

  useEffect(() => {
    controllerRef.current?.setState({
      mode: avatar.mode,
      expression: avatar.expression,
      motion: avatar.motion,
      subtitle: avatar.subtitle,
      lipSync: isSpeaking,
      lipSyncLevel,
    });
  }, [avatar.expression, avatar.mode, avatar.motion, avatar.subtitle, isSpeaking, lipSyncLevel]);

  const mouthOpen = Math.max(0.08, Math.min(1, lipSyncLevel || (isSpeaking ? 0.35 : 0.08)));

  return (
    <section className="avatar-stage" aria-label="Avatar">
      <div className={`live2d-layer ${isLive2DReady ? "is-ready" : ""}`} aria-hidden={!isLive2DReady}>
        <canvas ref={canvasRef} />
      </div>

      <div
        className={`avatar-orbit avatar-${avatar.mode} ${
          isLive2DReady ? "avatar-orbit-fallback-hidden" : ""
        }`}
      >
        <div className={`avatar-face expression-${avatar.expression}`}>
          <div className="avatar-brow avatar-brow-left" />
          <div className="avatar-brow avatar-brow-right" />
          <div className="avatar-eye avatar-eye-left" />
          <div className="avatar-eye avatar-eye-right" />
          <div
            className={`avatar-mouth ${isSpeaking ? "avatar-mouth-speaking" : ""}`}
            style={{ transform: `scaleY(${1 + mouthOpen * 1.8})` }}
          />
        </div>
        <div className="avatar-shadow" />
      </div>

      <div className="avatar-meta">
        <span className="status-pill">{status}</span>
        <span>{expressionLabel[avatar.expression] ?? avatar.expression}</span>
      </div>

      <p className="avatar-subtitle">{avatar.subtitle}</p>

      <button className="tool-button danger" type="button" onClick={onInterrupt}>
        <PauseCircle size={18} />
        打断
      </button>
    </section>
  );
}
