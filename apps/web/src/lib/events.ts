export type AvatarMode =
  | "sleeping"
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export type AvatarExpression =
  | "neutral"
  | "happy"
  | "curious"
  | "surprised"
  | "confused"
  | "concerned"
  | "thinking"
  | "sleepy";

export type CostMode = "sleep" | "low_cost" | "active" | "focus";

export interface EventEnvelope<TPayload = Record<string, unknown>> {
  id: string;
  type: string;
  session_id: string;
  ts: number;
  payload: TPayload;
}

export interface CostMeter {
  frames_uploaded: number;
  bytes_uploaded: number;
  vision_calls: number;
  llm_calls: number;
  asr_calls: number;
  tts_calls: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  estimated_cost_usd: number | null;
  mode: CostMode;
  last_latency_ms: number | null;
}

export interface FramePayload {
  frame_id: string;
  mime: "image/jpeg";
  width: number;
  height: number;
  quality: number;
  capture_reason:
    | "wake_snapshot"
    | "visual_question"
    | "scene_changed"
    | "manual_debug"
    | "focus_roi"
    | "periodic_low_cost";
  scene_hash: string;
  data_base64: string;
  prompt?: string;
}

export interface AvatarStatePayload {
  mode: AvatarMode;
  expression: AvatarExpression;
  motion: string;
  subtitle: string;
  lip_sync: boolean;
}

export function createEvent<TPayload>(
  type: string,
  sessionId: string,
  payload: TPayload,
): EventEnvelope<TPayload> {
  return {
    id: `evt_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`,
    type,
    session_id: sessionId,
    ts: Date.now(),
    payload,
  };
}

