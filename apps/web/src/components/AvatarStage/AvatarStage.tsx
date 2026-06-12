import { PauseCircle } from "lucide-react";

import { useAppStore } from "../../app/store";

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
  const isSpeaking = avatar.mode === "speaking";

  return (
    <section className="avatar-stage" aria-label="Avatar">
      <div className={`avatar-orbit avatar-${avatar.mode}`}>
        <div className={`avatar-face expression-${avatar.expression}`}>
          <div className="avatar-brow avatar-brow-left" />
          <div className="avatar-brow avatar-brow-right" />
          <div className="avatar-eye avatar-eye-left" />
          <div className="avatar-eye avatar-eye-right" />
          <div className={`avatar-mouth ${isSpeaking ? "avatar-mouth-speaking" : ""}`} />
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

