import { describe, expect, it } from "vitest";

import { encodePcm16 } from "./pcmRecorder";
import { LiveAudioGate, pcm16DurationMs, pcm16Rms } from "./voiceActivity";

function pcm(value: number, samples = 1600) {
  return encodePcm16(new Float32Array(samples).fill(value));
}

describe("voiceActivity helpers", () => {
  it("measures pcm16 rms and duration", () => {
    const chunk = pcm(0.5, 1600);
    expect(pcm16Rms(chunk)).toBeCloseTo(0.5, 3);
    expect(pcm16DurationMs(chunk, 16000)).toBe(100);
  });

  it("buffers pre-roll and starts sending after speech begins", () => {
    const gate = new LiveAudioGate({ preRollMs: 350, startThreshold: 0.05 });

    expect(gate.accept(pcm(0.001), 0).chunks).toHaveLength(0);
    expect(gate.accept(pcm(0.001), 100).chunks).toHaveLength(0);

    const decision = gate.accept(pcm(0.2), 200);
    expect(decision.state).toBe("speaking");
    expect(decision.chunks).toHaveLength(3);
    expect(decision.shouldStop).toBe(false);
  });

  it("stops without final when only initial silence was heard", () => {
    const gate = new LiveAudioGate({ initialSilenceMs: 250 });
    gate.accept(pcm(0), 0);
    gate.accept(pcm(0), 100);

    const decision = gate.accept(pcm(0), 300);
    expect(decision.state).toBe("initial_timeout");
    expect(decision.shouldStop).toBe(true);
    expect(decision.sendFinal).toBe(false);
    expect(decision.chunks).toHaveLength(0);
  });

  it("sends final after speech followed by silence", () => {
    const gate = new LiveAudioGate({ startThreshold: 0.05, continueThreshold: 0.02, silenceAfterSpeechMs: 250 });
    gate.accept(pcm(0.2), 0);
    gate.accept(pcm(0.2), 100);

    const decision = gate.accept(pcm(0), 400);
    expect(decision.state).toBe("silence");
    expect(decision.shouldStop).toBe(true);
    expect(decision.sendFinal).toBe(true);
    expect(decision.chunks).toHaveLength(1);
  });

  it("stops after speech when trailing mic noise stays above the old static threshold", () => {
    const gate = new LiveAudioGate({
      startThreshold: 0.008,
      continueThreshold: 0.004,
      minContinueThreshold: 0.0015,
      noiseMargin: 0.0025,
      peakDropRatio: 0.2,
      silenceAfterSpeechMs: 250,
    });
    gate.accept(pcm(0.05), 0);
    gate.accept(pcm(0.05), 100);
    gate.accept(pcm(0.006), 200);

    const decision = gate.accept(pcm(0.006), 400);
    expect(decision.state).toBe("silence");
    expect(decision.shouldStop).toBe(true);
    expect(decision.sendFinal).toBe(true);
  });

  it("caps long realtime turns", () => {
    const gate = new LiveAudioGate({ startThreshold: 0.05, maxTurnMs: 250 });
    gate.accept(pcm(0.2), 0);

    const decision = gate.accept(pcm(0.2), 300);
    expect(decision.state).toBe("max_turn");
    expect(decision.shouldStop).toBe(true);
    expect(decision.sendFinal).toBe(true);
  });
});
