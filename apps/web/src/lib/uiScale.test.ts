import { describe, expect, it } from "vitest";

import { clampScale, MAX_SCALE, MIN_SCALE, SCALE_STEP } from "./uiScale";

describe("clampScale", () => {
  it("keeps values inside the allowed zoom range", () => {
    expect(clampScale(1)).toBe(1);
    expect(clampScale(MIN_SCALE)).toBe(MIN_SCALE);
    expect(clampScale(MAX_SCALE)).toBe(MAX_SCALE);
  });

  it("clamps out-of-range values to the nearest bound", () => {
    expect(clampScale(0.1)).toBe(MIN_SCALE);
    expect(clampScale(5)).toBe(MAX_SCALE);
  });

  it("falls back to 1 for non-finite input", () => {
    expect(clampScale(Number.NaN)).toBe(1);
    expect(clampScale(Number.POSITIVE_INFINITY)).toBe(1);
    expect(clampScale(Number.NEGATIVE_INFINITY)).toBe(1);
  });

  it("steps stay within bounds after repeated zoom in/out", () => {
    let scale = 1;
    for (let i = 0; i < 100; i += 1) scale = clampScale(scale + SCALE_STEP);
    expect(scale).toBe(MAX_SCALE);
    for (let i = 0; i < 100; i += 1) scale = clampScale(scale - SCALE_STEP);
    expect(scale).toBe(MIN_SCALE);
  });
});
