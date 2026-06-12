const REALTIME_STOP_ERROR_CODES = new Set([
  "audio_turn_too_large",
  "empty_audio",
  "invalid_audio_chunk",
  "realtime_failed",
  "realtime_finish_failed",
  "realtime_input_idle_timeout",
  "realtime_open_failed",
  "realtime_send_failed",
  "realtime_stream_failed",
  "unsupported_realtime_audio",
]);

export interface ServerErrorPayload {
  code?: unknown;
  detail?: unknown;
}

export function shouldStopRealtimeAudioOnError(payload: unknown) {
  if (!payload || typeof payload !== "object") return false;
  const code = (payload as ServerErrorPayload).code;
  return typeof code === "string" && REALTIME_STOP_ERROR_CODES.has(code);
}
