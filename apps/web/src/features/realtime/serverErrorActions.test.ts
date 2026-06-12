import { describe, expect, it } from "vitest";

import { shouldStopRealtimeAudioOnError } from "./serverErrorActions";

describe("serverErrorActions", () => {
  it("stops local realtime audio for server-side realtime failures", () => {
    expect(shouldStopRealtimeAudioOnError({ code: "realtime_input_idle_timeout" })).toBe(true);
    expect(shouldStopRealtimeAudioOnError({ code: "realtime_send_failed" })).toBe(true);
    expect(shouldStopRealtimeAudioOnError({ code: "unsupported_realtime_audio" })).toBe(true);
  });

  it("does not stop local realtime audio for unrelated server errors", () => {
    expect(shouldStopRealtimeAudioOnError({ code: "tts_failed" })).toBe(false);
    expect(shouldStopRealtimeAudioOnError({ code: "session_mismatch" })).toBe(false);
    expect(shouldStopRealtimeAudioOnError({ detail: "missing code" })).toBe(false);
    expect(shouldStopRealtimeAudioOnError(null)).toBe(false);
  });
});
