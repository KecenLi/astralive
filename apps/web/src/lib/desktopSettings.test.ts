import { describe, expect, it } from "vitest";

import { mergeDesktopSettings, normalizeDesktopSettings } from "./desktopSettings";

describe("desktop settings", () => {
  it("normalizes invalid values to safe ranges", () => {
    const settings = normalizeDesktopSettings({
      avatarLayout: {
        main: { scale: 99, maxHeightPx: -1, yRatio: 4 },
      },
      proactiveChat: { minIntervalMinutes: 30, maxIntervalMinutes: 2 },
      voice: { inputGain: 99, tenDebounceOff: 2 },
    });

    expect(settings.avatarLayout.main.scale).toBe(2.25);
    expect(settings.avatarLayout.main.maxHeightPx).toBe(180);
    expect(settings.avatarLayout.main.yRatio).toBe(0.95);
    expect(settings.proactiveChat.maxIntervalMinutes).toBe(settings.proactiveChat.minIntervalMinutes);
    expect(settings.voice.inputGain).toBe(4);
    expect(settings.voice.tenDebounceOff).toBe(8);
  });

  it("deep merges nested patches", () => {
    const settings = mergeDesktopSettings(
      normalizeDesktopSettings({ avatarLayout: { main: { scale: 0.7, offsetX: 11 } } }),
      { avatarLayout: { main: { scale: 1.1 } } },
    );

    expect(settings.avatarLayout.main.scale).toBe(1.1);
    expect(settings.avatarLayout.main.offsetX).toBe(11);
  });
});
