import { describe, expect, it } from "vitest";

import {
  nextRealSpeechInputActive,
  shouldSuspendVisualAutoUpload,
} from "./conversationGates";

function visualSuspended(realSpeechInputActive: boolean) {
  return shouldSuspendVisualAutoUpload({
    realSpeechInputActive,
    conversationMode: true,
    liveAudioActive: true,
    voiceResponsePending: true,
    status: "speaking",
  });
}

describe("continuous conversation gates", () => {
  it("does not suspend visual auto-upload while listening for wake word without speech", () => {
    expect(visualSuspended(false)).toBe(false);
  });

  it("suspends visual auto-upload from speech start until final audio", () => {
    let active = nextRealSpeechInputActive(false, { type: "speech_start" });
    expect(visualSuspended(active)).toBe(true);

    active = nextRealSpeechInputActive(active, { type: "audio_final" });
    expect(visualSuspended(active)).toBe(false);
  });

  it("suspends on the first non-final audio chunk and restores on final", () => {
    let active = nextRealSpeechInputActive(false, { type: "audio_chunk", isFinal: false, hasAudio: true });
    expect(visualSuspended(active)).toBe(true);

    active = nextRealSpeechInputActive(active, { type: "audio_chunk", isFinal: true, hasAudio: false });
    expect(visualSuspended(active)).toBe(false);
  });
});
