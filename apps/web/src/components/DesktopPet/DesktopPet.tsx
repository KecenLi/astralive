import { MessageCircle, X } from "lucide-react";
import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";

import { describeLive2DError, Live2DAvatarController } from "../../features/avatar/avatarController";
import { useDesktopSettings } from "../../hooks/useDesktopSettings";
import { AvatarExpression, AvatarMode } from "../../lib/events";
import { LIVE2D_MODEL_URL } from "../../lib/env";

const petStates: Array<{
  mode: AvatarMode;
  expression: AvatarExpression;
  motion: string;
  subtitle: string;
}> = [
  { mode: "idle", expression: "happy", motion: "happy", subtitle: "小七在。" },
  { mode: "listening", expression: "curious", motion: "curious", subtitle: "我听着。" },
  { mode: "thinking", expression: "thinking", motion: "think", subtitle: "让我想想。" },
  { mode: "speaking", expression: "surprised", motion: "surprised", subtitle: "收到。" },
  { mode: "idle", expression: "neutral", motion: "idle", subtitle: "需要我就叫小七。" },
];

export function DesktopPet() {
  const { settings } = useDesktopSettings();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<Live2DAvatarController | null>(null);
  const bubbleTimerRef = useRef<number | null>(null);
  const initialLayoutRef = useRef(settings.avatarLayout.pet);
  const [ready, setReady] = useState(false);
  const [index, setIndex] = useState(0);
  const [bubbleVisible, setBubbleVisible] = useState(false);
  const [proactive, setProactive] = useState<{ text: string; prompt: string } | null>(null);
  const state = petStates[index % petStates.length];
  const label = useMemo(() => `${state.subtitle} 点击互动`, [state.subtitle]);
  const bubbleText = useMemo(
    () =>
      proactive?.text ||
      `${state.subtitle} ${ready ? "Live2D 已就绪" : "备用形象"}，拖动顶部区域可移动。`,
    [proactive?.text, ready, state.subtitle],
  );

  useEffect(() => {
    document.body.classList.add("pet-body");
    return () => {
      document.body.classList.remove("pet-body");
    };
  }, []);

  useEffect(() => {
    return () => {
      if (bubbleTimerRef.current !== null) window.clearTimeout(bubbleTimerRef.current);
    };
  }, []);

  useEffect(() => {
    return window.modvii?.pet.onNotify?.((payload) => {
      const next = {
        text: payload.text || "我有个小想法，点我聊一下。",
        prompt: payload.prompt || "",
      };
      setProactive(next);
      setBubbleVisible(true);
      if (bubbleTimerRef.current !== null) window.clearTimeout(bubbleTimerRef.current);
      bubbleTimerRef.current = window.setTimeout(() => {
        setBubbleVisible(false);
        bubbleTimerRef.current = null;
      }, 9000);
    }) ?? (() => undefined);
  }, []);

  useEffect(() => {
    if (!canvasRef.current || !LIVE2D_MODEL_URL) return;
    let disposed = false;
    const controller = new Live2DAvatarController();
    controllerRef.current = controller;

    async function mount() {
      try {
        await controller.mount(canvasRef.current as HTMLCanvasElement, LIVE2D_MODEL_URL, initialLayoutRef.current);
        if (!disposed) setReady(true);
      } catch (error) {
        console.warn(`Desktop pet Live2D failed to load; using fallback. ${describeLive2DError(error)}`);
        if (!disposed) setReady(false);
      }
    }

    void mount();
    return () => {
      disposed = true;
      controller.dispose();
      controllerRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    controllerRef.current?.setFitOptions(settings.avatarLayout.pet);
  }, [settings.avatarLayout.pet]);

  useEffect(() => {
    controllerRef.current?.setState({
      mode: state.mode,
      expression: state.expression,
      motion: state.motion,
      subtitle: state.subtitle,
      lipSync: state.mode === "speaking",
    });
  }, [state]);

  function interact() {
    if (proactive) {
      const payload = proactive;
      setProactive(null);
      setBubbleVisible(false);
      void window.modvii?.pet.acceptProactive?.(payload);
      return;
    }
    const next = (index + 1) % petStates.length;
    setIndex(next);
    setBubbleVisible(true);
    if (bubbleTimerRef.current !== null) window.clearTimeout(bubbleTimerRef.current);
    bubbleTimerRef.current = window.setTimeout(() => {
      setBubbleVisible(false);
      bubbleTimerRef.current = null;
    }, 2600);
  }

  function hidePet() {
    void window.modvii?.pet.hide();
  }

  function openMain(event: MouseEvent) {
    // Right-clicking the pet opens (shows/focuses) the main MODVII window.
    event.preventDefault();
    void window.modvii?.pet.openMain?.();
  }

  return (
    <main
      className="pet-root"
      aria-label="MODVII 桌宠"
      data-testid="desktop-pet"
      onContextMenu={openMain}
    >
      <div className="pet-drag-handle" aria-hidden="true" />
      <button className="pet-close" type="button" title="隐藏桌宠" onClick={hidePet}>
        <X size={16} />
      </button>
      <button className="pet-avatar" type="button" aria-label={label} onClick={interact}>
        <canvas ref={canvasRef} className={ready ? "is-ready" : ""} />
        <span className={`pet-fallback expression-${state.expression}${ready ? " is-hidden" : ""}`}>
          <span className="avatar-brow avatar-brow-left" />
          <span className="avatar-brow avatar-brow-right" />
          <span className="avatar-eye avatar-eye-left" />
          <span className="avatar-eye avatar-eye-right" />
          <span className="avatar-mouth" />
        </span>
      </button>
      {bubbleVisible && (
        <div className="pet-bubble" data-testid="pet-bubble" aria-live="polite">
          <MessageCircle size={15} />
          <span>{bubbleText}</span>
        </div>
      )}
    </main>
  );
}
