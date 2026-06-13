import { contextBridge, ipcRenderer } from "electron";

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
  },
  pet: {
    getState: () => ipcRenderer.invoke("pet:getState"),
    show: () => ipcRenderer.invoke("pet:show"),
    hide: () => ipcRenderer.invoke("pet:hide"),
    toggle: () => ipcRenderer.invoke("pet:toggle"),
  },
});
