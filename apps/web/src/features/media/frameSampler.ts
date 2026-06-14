import { FramePayload } from "../../lib/events";
import { normalizedHashDistance } from "./sceneHash";

export type VisualCaptureMode = "low_fps" | "continuous";
export type VisualCaptureActivity = "idle" | "active" | "focus";
export type VisualCaptureSource = "screen" | "camera";

export const DEFAULT_SCENE_HASH_THRESHOLD = 0.12;

export interface VisualCaptureProfile {
  idleFps: number;
  activeFps: number;
  focusFps: number;
  normalMaxWidth: number;
  normalMaxHeight: number;
  normalQuality: number;
  focusMaxWidth: number;
  focusMaxHeight: number;
  focusQuality: number;
}

export const VISUAL_CAPTURE_PROFILES: Record<VisualCaptureMode, VisualCaptureProfile> = {
  low_fps: {
    idleFps: 0.2,
    activeFps: 1,
    focusFps: 2,
    normalMaxWidth: 1280,
    normalMaxHeight: 720,
    normalQuality: 0.72,
    focusMaxWidth: 1600,
    focusMaxHeight: 900,
    focusQuality: 0.85,
  },
  continuous: {
    idleFps: 0.5,
    activeFps: 2,
    focusFps: 5,
    normalMaxWidth: 1280,
    normalMaxHeight: 720,
    normalQuality: 0.72,
    focusMaxWidth: 1600,
    focusMaxHeight: 900,
    focusQuality: 0.85,
  },
};

export function activityFromStatus(status: string): VisualCaptureActivity {
  if (status === "sleeping" || status === "idle") return "idle";
  return "active";
}

export function getFrameIntervalMs(mode: VisualCaptureMode, activity: VisualCaptureActivity): number {
  const profile = VISUAL_CAPTURE_PROFILES[mode];
  const fps =
    activity === "focus" ? profile.focusFps : activity === "active" ? profile.activeFps : profile.idleFps;
  return Math.max(100, Math.round(1000 / fps));
}

export function captureReasonFor(
  source: VisualCaptureSource,
  mode: VisualCaptureMode,
  activity: VisualCaptureActivity,
): FramePayload["capture_reason"] {
  if (activity === "focus") return source === "screen" ? "screen_focus" : "focus_roi";
  if (source === "camera") return "camera_stream";
  return mode === "low_fps" ? "screen_low_fps" : "screen_stream";
}

export function captureOptionsFor(mode: VisualCaptureMode, activity: VisualCaptureActivity) {
  const profile = VISUAL_CAPTURE_PROFILES[mode];
  if (activity === "focus") {
    return {
      quality: profile.focusQuality,
      maxWidth: profile.focusMaxWidth,
      maxHeight: profile.focusMaxHeight,
    };
  }
  return {
    quality: profile.normalQuality,
    maxWidth: profile.normalMaxWidth,
    maxHeight: profile.normalMaxHeight,
  };
}

export function shouldSendSceneHash(
  previous: string | null,
  next: string,
  activity: VisualCaptureActivity,
  threshold = DEFAULT_SCENE_HASH_THRESHOLD,
) {
  if (activity === "focus") return true;
  if (!previous || !next) return true;
  return normalizedHashDistance(previous, next) > threshold;
}
