import type { Approval, Artifact, DesktopSnapshot, DiagnosticExport, LedgerEvent, ResetPreview, ResetResult, Run, SystemStatus, Workspace } from "./types";
import { invoke } from "@tauri-apps/api/core";

export interface BridgeConfig { baseUrl: string; token?: string }

declare global {
  interface Window { __WEATHERFLOW_BRIDGE__?: BridgeConfig }
}

export function bridgeConfig(): BridgeConfig {
  return window.__WEATHERFLOW_BRIDGE__ ?? { baseUrl: "http://127.0.0.1:8765" };
}

export async function resolveBridgeConfig(): Promise<BridgeConfig> {
  if (window.__WEATHERFLOW_BRIDGE__) return window.__WEATHERFLOW_BRIDGE__;
  if ("__TAURI_INTERNALS__" in window) {
    return invoke<BridgeConfig>("daemon_bridge");
  }
  return bridgeConfig();
}

export class WeatherFlowClient {
  constructor(private readonly config: BridgeConfig = bridgeConfig()) {}

  private headers(): HeadersInit {
    return this.config.token ? { Authorization: `Bearer ${this.config.token}` } : {};
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...this.headers(), ...init?.headers },
    });
    if (!response.ok) throw new Error(`WeatherFlow bridge ${response.status}`);
    return response.json() as Promise<T>;
  }

  private scoped(path: string, workspaceId?: string | null): string {
    if (!workspaceId) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}workspace_id=${encodeURIComponent(workspaceId)}`;
  }

  snapshot(workspaceId?: string | null): Promise<DesktopSnapshot> { return this.request(this.scoped("/v1/desktop/snapshot", workspaceId)); }
  workspaces(): Promise<Workspace[]> { return this.request("/v1/workspaces"); }
  authorizeWorkspace(name: string, path: string): Promise<Workspace> {
    return this.request("/v1/workspaces", { method: "POST", body: JSON.stringify({ name, path }) });
  }
  runs(workspaceId?: string | null): Promise<Run[]> { return this.request(this.scoped("/v1/runs", workspaceId)); }
  approvals(): Promise<Approval[]> { return this.request("/v1/approvals"); }
  timeline(runId: string): Promise<LedgerEvent[]> { return this.request(`/v1/runs/${runId}/timeline`); }
  artifacts(runId: string): Promise<Artifact[]> { return this.request(`/v1/runs/${runId}/artifacts`); }
  cancel(runId: string): Promise<Run> { return this.request(`/v1/runs/${runId}/cancel`, { method: "POST" }); }
  createRun(userIntent: string, clientRequestId: string, workspaceId?: string | null, contextRunId?: string | null): Promise<Run> {
    return this.request("/v1/runs", {
      method: "POST",
      body: JSON.stringify({ user_intent: userIntent, client_request_id: clientRequestId, workspace_id: workspaceId, context_run_id: contextRunId }),
    });
  }
  decide(approvalId: string, decision: "approve" | "deny", version: number): Promise<unknown> {
    return this.request(`/v1/approvals/${approvalId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, expected_version: version, resume: true }),
    });
  }
  ingestSignal(signal: Record<string, unknown>, workspaceId?: string | null): Promise<unknown> {
    return this.request(this.scoped("/v1/rhythm/signals", workspaceId), { method: "POST", body: JSON.stringify(signal) });
  }
  status(workspaceId?: string | null): Promise<SystemStatus> { return this.request(this.scoped("/v1/system/status", workspaceId)); }
  completeOnboarding(enableMetadataSensor: boolean, workspaceId?: string | null): Promise<unknown> {
    return this.request(this.scoped("/v1/onboarding/complete", workspaceId), {
      method: "POST",
      body: JSON.stringify({
        confirm_local_ownership: true,
        enable_metadata_sensor: enableMetadataSensor,
      }),
    });
  }
  async artifactContent(artifactId: string): Promise<Blob> {
    const response = await fetch(`${this.config.baseUrl}/v1/artifacts/${artifactId}/content`, { headers: this.headers() });
    if (!response.ok) throw new Error(`WeatherFlow bridge ${response.status}`);
    return response.blob();
  }
  exportDiagnostics(workspaceId?: string | null): Promise<DiagnosticExport> {
    return this.request(this.scoped("/v1/diagnostics/export", workspaceId), { method: "POST" });
  }
  previewReset(category: string, workspaceId?: string | null): Promise<ResetPreview> {
    return this.request(this.scoped(`/v1/privacy/reset/${category}`, workspaceId));
  }
  reset(category: string, workspaceId?: string | null): Promise<ResetResult> {
    return this.request(this.scoped(`/v1/privacy/reset/${category}`, workspaceId), {
      method: "POST", body: JSON.stringify({ confirm: true }),
    });
  }

  events(cursor: string | null, onEvent: (event: LedgerEvent) => void, onRefresh: () => void): WebSocket {
    const url = new URL(this.config.baseUrl.replace(/^http/, "ws") + "/v1/events");
    if (cursor) url.searchParams.set("cursor", cursor);
    if (this.config.token) url.searchParams.set("token", this.config.token);
    const socket = new WebSocket(url);
    socket.onmessage = (message) => onEvent(JSON.parse(message.data as string) as LedgerEvent);
    socket.onclose = (event) => { if (event.code === 4409) onRefresh(); };
    return socket;
  }
}
