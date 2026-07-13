import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

async function nativeInvoke(command: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) await invoke(command);
  else window.dispatchEvent(new CustomEvent(`weatherflow:${command}`));
}

async function chooseWorkspaceDirectory(): Promise<string | null> {
  if ("__TAURI_INTERNALS__" in window) return invoke<string | null>("choose_workspace_directory");
  return window.prompt("Absolute project directory")?.trim() || null;
}

async function openConnectorUrl(url: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) await invoke("open_connector_url", { url });
  else window.dispatchEvent(new CustomEvent("weatherflow:open_connector_url", { detail: { url } }));
}

export type CredentialProvider =
  | "minimax"
  | "deepseek"
  | "moonshot"
  | "qwen"
  | "zhipu"
  | "siliconflow"
  | "stepfun"
  | "composio";

export interface CredentialStatus {
  provider: CredentialProvider;
  key_present: boolean;
}

function requireNativeCredentialBridge(): void {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("native credential bridge unavailable");
  }
}

export const nativeCredentials = {
  async set(provider: CredentialProvider, secret: string): Promise<CredentialStatus> {
    requireNativeCredentialBridge();
    return invoke<CredentialStatus>("credential_set", { provider, secret });
  },
  async delete(provider: CredentialProvider): Promise<CredentialStatus> {
    requireNativeCredentialBridge();
    return invoke<CredentialStatus>("credential_delete", { provider });
  },
  async status(provider: CredentialProvider): Promise<CredentialStatus> {
    if (!("__TAURI_INTERNALS__" in window)) return { provider, key_present: false };
    return invoke<CredentialStatus>("credential_status", { provider });
  },
};

export const nativeWindows = {
  startCompanionDrag: async () => {
    if ("__TAURI_INTERNALS__" in window) await getCurrentWindow().startDragging();
    else window.dispatchEvent(new CustomEvent("weatherflow:start_dragging"));
  },
  openCapsule: () => nativeInvoke("open_capsule"),
  closeCapsule: () => nativeInvoke("close_capsule"),
  openCockpit: () => nativeInvoke("open_cockpit"),
  openConnectorUrl,
  chooseWorkspaceDirectory,
};
