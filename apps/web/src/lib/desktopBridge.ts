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

export interface DesktopSettings {
  firstRunComplete?: boolean;
  autostartAsked?: boolean;
  autostartEnabled?: boolean;
  captureMode?: "low_fps" | "continuous";
  petEnabled?: boolean;
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
    set: (settings: Partial<DesktopSettings>) => Promise<DesktopSettings>;
  };
  pet: {
    getState: () => Promise<{ visible: boolean }>;
    show: () => Promise<{ visible: boolean }>;
    hide: () => Promise<{ visible: boolean }>;
    toggle: () => Promise<{ visible: boolean }>;
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
  if (!window.modvii) return {};
  return window.modvii.settings.get();
}

export async function setDesktopSettings(settings: Partial<DesktopSettings>) {
  if (!window.modvii) return settings;
  return window.modvii.settings.set(settings);
}
