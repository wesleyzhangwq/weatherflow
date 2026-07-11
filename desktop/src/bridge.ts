import type { Approval, Artifact, DesktopSnapshot, LedgerEvent, Run } from "./types";

export interface BridgeConfig { baseUrl: string; token?: string }

declare global {
  interface Window { __WEATHERFLOW_BRIDGE__?: BridgeConfig }
}

export function bridgeConfig(): BridgeConfig {
  return window.__WEATHERFLOW_BRIDGE__ ?? { baseUrl: "http://127.0.0.1:8765" };
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

  snapshot(): Promise<DesktopSnapshot> { return this.request("/v1/desktop/snapshot"); }
  approvals(): Promise<Approval[]> { return this.request("/v1/approvals"); }
  timeline(runId: string): Promise<LedgerEvent[]> { return this.request(`/v1/runs/${runId}/timeline`); }
  artifacts(runId: string): Promise<Artifact[]> { return this.request(`/v1/runs/${runId}/artifacts`); }
  createRun(userIntent: string, clientRequestId: string): Promise<Run> {
    return this.request("/v1/runs", {
      method: "POST",
      body: JSON.stringify({ user_intent: userIntent, client_request_id: clientRequestId }),
    });
  }
  decide(approvalId: string, decision: "approve" | "deny", version: number): Promise<unknown> {
    return this.request(`/v1/approvals/${approvalId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, expected_version: version, resume: true }),
    });
  }
  ingestSignal(signal: Record<string, unknown>): Promise<unknown> {
    return this.request("/v1/rhythm/signals", { method: "POST", body: JSON.stringify(signal) });
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
