import { describe, expect, it } from "vitest";

import { extractWakeRequest } from "./wakePhrase";

describe("extractWakeRequest", () => {
  it("detects the MODVII wake word", () => {
    expect(extractWakeRequest("小七", "小七")).toEqual({ matched: true, requestText: "" });
  });

  it("extracts the request after the wake word", () => {
    expect(extractWakeRequest("小七，帮我看一下屏幕", "小七")).toEqual({
      matched: true,
      requestText: "帮我看一下屏幕",
    });
  });

  it("ignores unrelated speech", () => {
    expect(extractWakeRequest("今天不用助手", "小七")).toEqual({ matched: false, requestText: "" });
  });
});
