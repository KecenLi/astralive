import { describe, expect, it } from "vitest";

import { useAppStore } from "./store";

describe("app store visual context", () => {
  it("keeps camera, screen, and fused summaries separately", () => {
    useAppStore.setState({
      visualSummary: "",
      cameraVisualSummary: "",
      screenVisualSummary: "",
      fusedVisualSummary: "",
    });

    useAppStore.getState().setVisualContext({
      camera: "用户在摄像头前。",
      screen: "屏幕上是代码编辑器。",
      fused: "摄像头：用户在摄像头前。\n屏幕：屏幕上是代码编辑器。",
    });

    const state = useAppStore.getState();
    expect(state.cameraVisualSummary).toBe("用户在摄像头前。");
    expect(state.screenVisualSummary).toBe("屏幕上是代码编辑器。");
    expect(state.fusedVisualSummary).toContain("摄像头：用户在摄像头前。");
    expect(state.visualSummary).toBe(state.fusedVisualSummary);
  });
});
