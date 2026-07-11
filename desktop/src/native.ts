import { invoke } from "@tauri-apps/api/core";

async function nativeInvoke(command: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) await invoke(command);
  else window.dispatchEvent(new CustomEvent(`weatherflow:${command}`));
}

export const nativeWindows = {
  openCapsule: () => nativeInvoke("open_capsule"),
  closeCapsule: () => nativeInvoke("close_capsule"),
  openCockpit: () => nativeInvoke("open_cockpit"),
};
