import {
  DesktopSettings,
  DesktopSettingsPatch,
  normalizeDesktopSettings,
} from "./desktopSettings";

export interface DesktopScreenSource {
  id: string;
  name: string;
}

export interface DesktopPermissionResult {
  mic: boolean;
  camera: boolean;
  screen: boolean;
  errors: Record<string, string>;
}

export interface ModviiDesktopBridge {
  runtime: {
    getBackendUrl: () => Promise<string>;
    getBackendStatus: () => Promise<{ ready: boolean; url: string; error?: string }>;
  };
  screen: {
    getPrimarySource: () => Promise<DesktopScreenSource>;
  };
  autostart: {
    get: () => Promise<boolean>;
    set: (enabled: boolean) => Promise<boolean>;
  };
  settings: {
    get: () => Promise<DesktopSettings>;
    set: (settings: DesktopSettingsPatch) => Promise<DesktopSettings>;
    onChanged?: (handler: (settings: DesktopSettings) => void) => () => void;
  };
  pet: {
    getState: () => Promise<{ visible: boolean }>;
    show: () => Promise<{ visible: boolean }>;
    hide: () => Promise<{ visible: boolean }>;
    toggle: () => Promise<{ visible: boolean }>;
    openMain?: () => Promise<{ opened: boolean }>;
    notify?: (payload: { text?: string; prompt?: string }) => Promise<{ visible: boolean }>;
    acceptProactive?: (payload: { text?: string; prompt?: string }) => Promise<boolean>;
    onNotify?: (handler: (payload: { text?: string; prompt?: string }) => void) => () => void;
    onProactiveAccepted?: (handler: (payload: { text?: string; prompt?: string }) => void) => () => void;
  };
}

declare global {
  interface Window {
    modvii?: ModviiDesktopBridge;
  }
}

export function isDesktopRuntime() {
  return Boolean(window.modvii);
}

export async function getDesktopSettings(): Promise<DesktopSettings> {
  if (!window.modvii) return normalizeDesktopSettings({});
  return normalizeDesktopSettings(await window.modvii.settings.get());
}

export async function setDesktopSettings(settings: DesktopSettingsPatch) {
  if (!window.modvii) return normalizeDesktopSettings(settings as Partial<DesktopSettings>);
  return normalizeDesktopSettings(await window.modvii.settings.set(settings));
}

export function onDesktopSettingsChanged(handler: (settings: DesktopSettings) => void) {
  return window.modvii?.settings.onChanged?.((settings) => handler(normalizeDesktopSettings(settings))) ?? (() => undefined);
}
