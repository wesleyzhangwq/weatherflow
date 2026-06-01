/**
 * Preload script — exposes safe IPC bridge to renderer.
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("wfBridge", {
  onHypothesisUpdate: (callback: (data: any) => void) => {
    ipcRenderer.on("hypothesis-update", (_event, data) => callback(data));
  },
  onOpenChat: (callback: () => void) => {
    ipcRenderer.on("open-chat", () => callback());
  },
  toggleChat: (show: boolean) => {
    ipcRenderer.send("toggle-chat", show);
  },
  sendHypothesisUpdate: (data: any) => {
    ipcRenderer.send("hypothesis-update", data);
  },
});
