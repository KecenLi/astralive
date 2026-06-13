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

  it("detects the wake word in the middle of a sentence", () => {
    expect(extractWakeRequest("我刚才在想小七帮我总结屏幕", "小七")).toEqual({
      matched: true,
      requestText: "帮我总结屏幕",
    });
  });

  it("accepts common ASR variants and spaces", () => {
    expect(extractWakeRequest("那个 小 7 ，打开监听", "小七")).toEqual({
      matched: true,
      requestText: "打开监听",
    });
    expect(extractWakeRequest("晓琪，读一下聊天记录", "小七")).toEqual({
      matched: true,
      requestText: "读一下聊天记录",
    });
  });

  it("ignores unrelated speech", () => {
    expect(extractWakeRequest("今天不用助手", "小七")).toEqual({ matched: false, requestText: "" });
  });
});
