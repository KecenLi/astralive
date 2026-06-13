import { describe, expect, it } from "vitest";

import { computeAvatarFit } from "./avatarFit";

describe("computeAvatarFit", () => {
  it("caps fullscreen avatar height", () => {
    const fit = computeAvatarFit({
      mode: "main",
      parentWidth: 1920,
      parentHeight: 1080,
      modelWidth: 900,
      modelHeight: 1800,
      layout: { scale: 2, maxHeightPx: 760, widthFill: 1, heightFill: 1 },
    });

    expect(fit.scale * 1800).toBeLessThanOrEqual(760);
  });

  it("applies offsets without changing scale", () => {
    const base = computeAvatarFit({
      mode: "pet",
      parentWidth: 340,
      parentHeight: 500,
      modelWidth: 600,
      modelHeight: 1000,
      layout: { offsetX: 0, offsetY: 0 },
    });
    const shifted = computeAvatarFit({
      mode: "pet",
      parentWidth: 340,
      parentHeight: 500,
      modelWidth: 600,
      modelHeight: 1000,
      layout: { offsetX: 25, offsetY: -30 },
    });

    expect(shifted.scale).toBe(base.scale);
    expect(shifted.x).toBe(base.x + 25);
    expect(shifted.y).toBe(base.y - 30);
  });
});
