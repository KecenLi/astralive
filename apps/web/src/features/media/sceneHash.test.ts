import { describe, expect, it } from "vitest";

import { hammingDistance, normalizedHashDistance } from "./sceneHash";

describe("scene hash", () => {
  it("computes hamming distance", () => {
    expect(hammingDistance("1010", "1110")).toBe(1);
  });

  it("normalizes distance", () => {
    expect(normalizedHashDistance("0000", "1111")).toBe(1);
  });
});

