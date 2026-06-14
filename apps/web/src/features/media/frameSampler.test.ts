import { describe, expect, it } from "vitest";

import {
  activityFromStatus,
  captureOptionsFor,
  captureReasonFor,
  DEFAULT_SCENE_HASH_THRESHOLD,
  getFrameIntervalMs,
  sceneHashDistance,
  shouldBypassSceneDedupe,
  shouldSendSceneHash,
} from "./frameSampler";

describe("frameSampler", () => {
  it("uses the planned low-fps and continuous cadences", () => {
    expect(getFrameIntervalMs("low_fps", "idle")).toBe(5000);
    expect(getFrameIntervalMs("low_fps", "active")).toBe(1000);
    expect(getFrameIntervalMs("low_fps", "focus")).toBe(500);
    expect(getFrameIntervalMs("continuous", "idle")).toBe(2000);
    expect(getFrameIntervalMs("continuous", "active")).toBe(500);
    expect(getFrameIntervalMs("continuous", "focus")).toBe(200);
  });

  it("maps app status to capture activity", () => {
    expect(activityFromStatus("sleeping")).toBe("idle");
    expect(activityFromStatus("idle")).toBe("idle");
    expect(activityFromStatus("listening")).toBe("active");
    expect(activityFromStatus("speaking")).toBe("active");
  });

  it("emits explicit capture reasons for source and mode", () => {
    expect(captureReasonFor("screen", "low_fps", "active")).toBe("screen_low_fps");
    expect(captureReasonFor("screen", "continuous", "active")).toBe("screen_stream");
    expect(captureReasonFor("camera", "continuous", "active")).toBe("camera_stream");
    expect(captureReasonFor("screen", "continuous", "focus")).toBe("screen_focus");
    expect(captureReasonFor("camera", "continuous", "focus")).toBe("focus_roi");
  });

  it("uses higher quality for focus frames", () => {
    expect(captureOptionsFor("continuous", "active")).toMatchObject({
      maxWidth: 1280,
      quality: 0.72,
    });
    expect(captureOptionsFor("continuous", "focus")).toMatchObject({
      maxWidth: 1600,
      quality: 0.85,
    });
  });

  it("uses normalized scene hash distance for duplicate filtering", () => {
    expect(DEFAULT_SCENE_HASH_THRESHOLD).toBe(0.12);
    expect(shouldSendSceneHash(null, "0000", "active")).toBe(true);
    expect(shouldSendSceneHash("0000000000000000", "1000000000000000", "active")).toBe(false);
    expect(shouldSendSceneHash("00000000", "10000000", "active")).toBe(true);
    expect(sceneHashDistance("0000", "1000")).toBe(0.25);
    expect(sceneHashDistance(null, "1000")).toBeNull();
  });

  it("honors custom scene hash thresholds while focus always sends", () => {
    expect(shouldSendSceneHash("0000", "1000", "active", 0.5)).toBe(false);
    expect(shouldSendSceneHash("0000", "1000", "active", 0.25)).toBe(false);
    expect(shouldSendSceneHash("0000", "1000", "active", 0.24)).toBe(true);
    expect(shouldSendSceneHash("0000", "0000", "focus", 1)).toBe(true);
  });

  it("bypasses scene dedupe for explicit manual and focus captures", () => {
    expect(shouldBypassSceneDedupe("screen_low_fps")).toBe(false);
    expect(shouldBypassSceneDedupe("screen_low_fps", true)).toBe(true);
    expect(shouldBypassSceneDedupe("visual_question")).toBe(true);
    expect(shouldBypassSceneDedupe("screen_focus")).toBe(true);
    expect(shouldBypassSceneDedupe("focus_roi")).toBe(true);
    expect(shouldBypassSceneDedupe("manual_debug")).toBe(true);
  });
});
