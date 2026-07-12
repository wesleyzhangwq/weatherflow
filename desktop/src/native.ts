import { invoke } from "@tauri-apps/api/core";

async function nativeInvoke(command: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) await invoke(command);
  else window.dispatchEvent(new CustomEvent(`weatherflow:${command}`));
}

async function chooseWorkspaceDirectory(): Promise<string | null> {
  if ("__TAURI_INTERNALS__" in window) return invoke<string | null>("choose_workspace_directory");
  return window.prompt("Absolute project directory")?.trim() || null;
}

export const nativeWindows = {
  openCapsule: () => nativeInvoke("open_capsule"),
  closeCapsule: () => nativeInvoke("close_capsule"),
  openCockpit: () => nativeInvoke("open_cockpit"),
  chooseWorkspaceDirectory,
};
