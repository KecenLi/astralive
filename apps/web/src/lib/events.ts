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

export interface AudioCapabilities {
  asr_provider: string;
  tts_provider: string;
  realtime_provider: string;
  input_sample_rate: number;
  output_sample_rate: number;
  channels: number;
  server_tts: boolean;
  server_realtime_audio: boolean;
  realtime_input_idle_timeout_seconds?: number;
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

export interface AudioChunkPayload {
  chunk_id: string;
  mime: string;
  sample_rate: number;
  channels: number;
  encoding: "pcm_s16le" | "wav" | "mp3" | "webm_opus" | "unknown";
  data_base64: string;
  is_final: boolean;
  metadata?: Record<string, unknown>;
}

export interface AssistantAudioPayload extends AudioChunkPayload {
  source?: "tts" | "realtime" | string;
  duration_ms?: number | null;
}

export interface AvatarStatePayload {
  mode: AvatarMode;
  expression: AvatarExpression;
  motion: string;
  subtitle: string;
  lip_sync: boolean;
}

export function createId(prefix: string) {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${random.slice(0, 16)}`;
}

export function createEvent<TPayload>(
  type: string,
  sessionId: string,
  payload: TPayload,
): EventEnvelope<TPayload> {
  return {
    id: createId("evt"),
    type,
    session_id: sessionId,
    ts: Date.now(),
    payload,
  };
}
