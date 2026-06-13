import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

function subscribe(channel: string, handler: (payload: unknown) => void) {
  const listener = (_event: IpcRendererEvent, payload: unknown) => handler(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("modvii", {
  runtime: {
    getBackendUrl: () => ipcRenderer.invoke("runtime:getBackendUrl"),
    getBackendStatus: () => ipcRenderer.invoke("runtime:getBackendStatus"),
  },
  screen: {
    getPrimarySource: () => ipcRenderer.invoke("screen:getPrimarySource"),
  },
  autostart: {
    get: () => ipcRenderer.invoke("autostart:get"),
    set: (enabled: boolean) => ipcRenderer.invoke("autostart:set", enabled),
  },
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (settings: Record<string, unknown>) => ipcRenderer.invoke("settings:set", settings),
    onChanged: (handler: (settings: unknown) => void) => subscribe("settings:changed", handler),
  },
  pet: {
    getState: () => ipcRenderer.invoke("pet:getState"),
    show: () => ipcRenderer.invoke("pet:show"),
    hide: () => ipcRenderer.invoke("pet:hide"),
    toggle: () => ipcRenderer.invoke("pet:toggle"),
    notify: (payload: { text?: string; prompt?: string }) => ipcRenderer.invoke("pet:notify", payload),
    acceptProactive: (payload: { text?: string; prompt?: string }) =>
      ipcRenderer.invoke("pet:acceptProactive", payload),
    onNotify: (handler: (payload: unknown) => void) => subscribe("pet:notify", handler),
    onProactiveAccepted: (handler: (payload: unknown) => void) =>
      subscribe("pet:proactiveAccepted", handler),
  },
});
