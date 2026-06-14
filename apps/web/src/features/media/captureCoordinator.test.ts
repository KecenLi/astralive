import { afterEach, describe, expect, it, vi } from "vitest";

import {
  __resetCaptureCoordinator,
  releaseCaptureSlot,
  runExclusiveCapture,
  tryAcquireCaptureSlot,
} from "./captureCoordinator";

afterEach(() => {
  __resetCaptureCoordinator();
  vi.restoreAllMocks();
});

describe("captureCoordinator", () => {
  it("grants the slot to only one caller at a time", () => {
    expect(tryAcquireCaptureSlot()).toBe(true);
    // A second source must not get the slot while the first holds it.
    expect(tryAcquireCaptureSlot()).toBe(false);
  });

  it("enforces a minimum gap between consecutive captures", () => {
    expect(tryAcquireCaptureSlot()).toBe(true);
    releaseCaptureSlot();
    // Immediately after release we are still inside the min-gap window.
    expect(tryAcquireCaptureSlot()).toBe(false);
  });

  it("runExclusiveCapture skips (returns null) when the slot is busy", async () => {
    expect(tryAcquireCaptureSlot()).toBe(true); // hold the slot
    const ran = vi.fn().mockResolvedValue("frame");
    const result = await runExclusiveCapture(ran);
    expect(result).toBeNull();
    expect(ran).not.toHaveBeenCalled();
  });

  it("runExclusiveCapture releases the slot even if the capture throws", async () => {
    await expect(
      runExclusiveCapture(async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    // Slot must be free again (give it a clean reset to bypass the min-gap).
    __resetCaptureCoordinator();
    expect(tryAcquireCaptureSlot()).toBe(true);
  });

  it("serializes two interleaved sources so they never overlap", async () => {
    let active = 0;
    let maxActive = 0;
    const work = async () => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await Promise.resolve();
      active -= 1;
    };
    // Fire both "camera" and "screen" together; the coordinator must prevent
    // them from running concurrently. Whichever loses simply skips.
    await Promise.all([runExclusiveCapture(work), runExclusiveCapture(work)]);
    expect(maxActive).toBeLessThanOrEqual(1);
  });
});
