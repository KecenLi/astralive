import { describe, expect, it } from "vitest";

import { shouldFinishResponseTurn } from "./responseAudioTurn";

describe("response audio turn gate", () => {
  it("blocks idle finish while streamed response audio is expected", () => {
    expect(
      shouldFinishResponseTurn({
        voiceResponsePending: true,
        assistantAudioDone: false,
        responseAudioTurnInProgress: true,
        playerActive: false,
      }),
    ).toBe(false);
  });

  it("finishes after audio.done when playback is already idle", () => {
    expect(
      shouldFinishResponseTurn({
        voiceResponsePending: true,
        assistantAudioDone: true,
        responseAudioTurnInProgress: false,
        playerActive: false,
      }),
    ).toBe(true);
  });

  it("waits for playback idle when audio.done arrives before the final chunk ends", () => {
    expect(
      shouldFinishResponseTurn({
        voiceResponsePending: true,
        assistantAudioDone: true,
        responseAudioTurnInProgress: false,
        playerActive: true,
      }),
    ).toBe(false);
  });

  it("keeps single-block audio compatible when no streamed-audio gate is active", () => {
    expect(
      shouldFinishResponseTurn({
        voiceResponsePending: true,
        assistantAudioDone: false,
        responseAudioTurnInProgress: false,
        playerActive: false,
      }),
    ).toBe(true);
  });
});
