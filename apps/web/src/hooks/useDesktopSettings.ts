import { useCallback, useEffect, useState } from "react";

import {
  getDesktopSettings,
  onDesktopSettingsChanged,
  setDesktopSettings,
} from "../lib/desktopBridge";
import {
  DEFAULT_DESKTOP_SETTINGS,
  DesktopSettings,
  DesktopSettingsPatch,
  mergeDesktopSettings,
  normalizeDesktopSettings,
} from "../lib/desktopSettings";

export function useDesktopSettings() {
  const [settings, setSettingsState] = useState<DesktopSettings>(DEFAULT_DESKTOP_SETTINGS);

  useEffect(() => {
    let disposed = false;
    void getDesktopSettings().then((next) => {
      if (!disposed) setSettingsState(normalizeDesktopSettings(next));
    });
    const unsubscribe = onDesktopSettingsChanged((next) => {
      if (!disposed) setSettingsState(normalizeDesktopSettings(next));
    });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, []);

  const patchSettings = useCallback(async (patch: DesktopSettingsPatch) => {
    setSettingsState((current) => mergeDesktopSettings(current, patch));
    const persisted = await setDesktopSettings(patch);
    setSettingsState(normalizeDesktopSettings(persisted));
    return persisted;
  }, []);

  return { settings, patchSettings };
}
