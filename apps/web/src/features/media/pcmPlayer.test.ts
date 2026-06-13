import { describe, expect, it } from "vitest";

import { calculateLipSyncEnvelope } from "./pcmPlayer";

describe("lip sync envelope", () => {
  it("keeps silence closed", () => {
    const envelope = calculateLipSyncEnvelope(new Float32Array(2400), 24000, 1, 50);

    expect(envelope.length).toBe(2);
    expect(Math.max(...envelope.map((point) => point.level))).toBe(0);
  });

  it("opens the mouth for audible speech energy", () => {
    const samples = new Float32Array(2400);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = index % 2 === 0 ? 0.42 : -0.42;
    }

    const envelope = calculateLipSyncEnvelope(samples, 24000, 1, 50);

    expect(envelope[0].offsetMs).toBe(0);
    expect(Math.max(...envelope.map((point) => point.level))).toBeGreaterThan(0.65);
  });

  it("handles interleaved stereo samples", () => {
    const frames = 1200;
    const samples = new Float32Array(frames * 2);
    for (let frame = 0; frame < frames; frame += 1) {
      samples[frame * 2] = 0.35;
      samples[frame * 2 + 1] = -0.35;
    }

    const envelope = calculateLipSyncEnvelope(samples, 24000, 2, 25);

    expect(envelope.length).toBe(2);
    expect(envelope[1].offsetMs).toBe(25);
    expect(envelope[1].level).toBeGreaterThan(envelope[0].level);
  });
});
