import type { ActivityExport, ActivityHeartbeat, ActivityInferenceJob, ActivityInterval, ActivityPreferences, ActivitySummary, Approval, Artifact, Automation, AutomationRunLink, AutomationSchedule, ConnectionAttempt, ConnectHandoff, ConnectorKind, ConnectorSnapshot, ConnectorStatus, DesktopSnapshot, DiagnosticExport, InstallApprovalRequest, LedgerEvent, MCPPreset, ModelConfigurationResponse, ModelConfigureInput, ModelProviderPreset, ProviderModelCatalog, ResetPreview, ResetResult, RhythmInsights, Run, Session, SkillCatalogEntry, SystemStatus, ToolMode, Workspace } from "./types";
import { invoke } from "@tauri-apps/api/core";

export interface BridgeConfig { baseUrl: string; token?: string }

declare global {
  interface Window { __WEATHERFLOW_BRIDGE__?: BridgeConfig }
}

export function bridgeConfig(): BridgeConfig {
  return explicitBridgeConfig() ?? {
    baseUrl: import.meta.env.VITE_WEATHERFLOW_BRIDGE_URL ?? "http://127.0.0.1:8765",
  };
}

export async function resolveBridgeConfig(): Promise<BridgeConfig> {
  if (!("__TAURI_INTERNALS__" in window)) return bridgeConfig();
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const embedded = explicitBridgeConfig();
    if (embedded) return embedded;
    try {
      return await invoke<BridgeConfig>("daemon_bridge");
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
  }
  throw new Error("authenticated WeatherFlow daemon bridge unavailable");
}

function explicitBridgeConfig(): BridgeConfig | null {
  return window.__WEATHERFLOW_BRIDGE__ ?? null;
}

export class WeatherFlowClient {
  constructor(private readonly config: BridgeConfig) {}

  private headers(): HeadersInit {
    return this.config.token ? { Authorization: `Bearer ${this.config.token}` } : {};
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...this.headers(), ...init?.headers },
    });
    if (!response.ok) throw new Error(`WeatherFlow bridge ${response.status}`);
    if (response.status === 204) return undefined as T;
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
  sessions(workspaceId: string): Promise<Session[]> { return this.request(this.scoped("/v1/sessions", workspaceId)); }
  createSession(workspaceId: string): Promise<Session> {
    return this.request("/v1/sessions", { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });
  }
  updateSession(sessionId: string, workspaceId: string, update: { title?: string; pinned?: boolean }): Promise<Session> {
    return this.request(this.scoped(`/v1/sessions/${encodeURIComponent(sessionId)}`, workspaceId), { method: "PATCH", body: JSON.stringify(update) });
  }
  deleteSession(sessionId: string, workspaceId: string): Promise<void> {
    return this.request(this.scoped(`/v1/sessions/${encodeURIComponent(sessionId)}`, workspaceId), { method: "DELETE" });
  }
  approvals(): Promise<Approval[]> { return this.request("/v1/approvals"); }
  timeline(runId: string): Promise<LedgerEvent[]> { return this.request(`/v1/runs/${runId}/timeline`); }
  artifacts(runId: string): Promise<Artifact[]> { return this.request(`/v1/runs/${runId}/artifacts`); }
  cancel(runId: string): Promise<Run> { return this.request(`/v1/runs/${runId}/cancel`, { method: "POST" }); }
  createRun(userIntent: string, clientRequestId: string, workspaceId?: string | null, contextRunId?: string | null, sessionId?: string | null, toolMode: ToolMode = "ask"): Promise<Run> {
    return this.request("/v1/runs", {
      method: "POST",
      body: JSON.stringify({ user_intent: userIntent, client_request_id: clientRequestId, workspace_id: workspaceId, context_run_id: contextRunId, ...(sessionId !== undefined ? { session_id: sessionId } : {}), tool_mode: toolMode }),
    });
  }
  decide(approvalId: string, decision: "approve" | "deny", version: number, workspaceId?: string): Promise<unknown> {
    return this.request(`/v1/approvals/${approvalId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, expected_version: version, resume: true, ...(workspaceId ? { workspace_id: workspaceId } : {}) }),
    });
  }
  ingestSignal(signal: Record<string, unknown>, workspaceId?: string | null): Promise<unknown> {
    return this.request(this.scoped("/v1/rhythm/signals", workspaceId), { method: "POST", body: JSON.stringify(signal) });
  }
  activityPreferences(): Promise<ActivityPreferences> { return this.request("/v1/activity/preferences"); }
  updateActivityPreferences(preferences: Omit<ActivityPreferences, "version">, expectedVersion: number): Promise<ActivityPreferences> {
    return this.request("/v1/activity/preferences", { method: "PUT", body: JSON.stringify({ ...preferences, expected_version: expectedVersion }) });
  }
  ingestActivityHeartbeat(heartbeat: ActivityHeartbeat): Promise<unknown> {
    return this.request("/v1/activity/heartbeats", { method: "POST", body: JSON.stringify(heartbeat) });
  }
  activitySummary(start: Date, end: Date): Promise<ActivitySummary> {
    const query = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
    return this.request(`/v1/activity/summary?${query}`);
  }
  async activityEvents(start: Date, end: Date): Promise<ActivityInterval[]> {
    const events: ActivityInterval[] = [];
    const pageSize = 10_000;
    for (let offset = 0; ; offset += pageSize) {
      const query = new URLSearchParams({
        start: start.toISOString(),
        end: end.toISOString(),
        limit: String(pageSize),
        offset: String(offset),
      });
      const page = await this.request<ActivityInterval[]>(`/v1/activity/events?${query}`);
      events.push(...page);
      if (page.length < pageSize) return events;
    }
  }
  async activityInferenceHistory(limit = 100): Promise<ActivityInferenceJob[]> {
    const jobs = await this.request<ActivityInferenceJob[]>(`/v1/activity/inference-jobs?limit=${limit}`);
    if (!jobs.length) return jobs;
    const latest = await this.request<ActivityInferenceJob>(`/v1/activity/inference-jobs/${encodeURIComponent(jobs[0].id)}`);
    return [latest, ...jobs.slice(1)];
  }
  activityExport(start: Date, end: Date): Promise<ActivityExport> {
    const query = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
    return this.request(`/v1/activity/export?${query}`);
  }
  deleteActivity(start: Date, end: Date): Promise<{ deleted: number }> {
    const query = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
    return this.request(`/v1/activity/events?${query}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) });
  }
  rhythmInsights(workspaceId?: string | null): Promise<RhythmInsights> { return this.request(this.scoped("/v1/rhythm/insights", workspaceId)); }
  status(workspaceId?: string | null): Promise<SystemStatus> { return this.request(this.scoped("/v1/system/status", workspaceId)); }
  async modelProviders(): Promise<ModelProviderPreset[]> { return (await this.request<{ providers: ModelProviderPreset[] }>("/v1/models/providers")).providers; }
  providerModels(provider: string): Promise<ProviderModelCatalog> {
    return this.request(`/v1/models/providers/${encodeURIComponent(provider)}/models`);
  }
  configureModel(configuration: ModelConfigureInput, workspaceId?: string | null): Promise<ModelConfigurationResponse> {
    return this.request(this.scoped("/v1/models/configure", workspaceId), { method: "POST", body: JSON.stringify(configuration) });
  }
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
  connectors(workspaceId?: string | null): Promise<ConnectorStatus[]> { return this.request(this.scoped("/v1/connectors", workspaceId)); }
  configureConnectors(): Promise<{ configured: boolean }> {
    return this.request("/v1/connectors/configure", { method: "POST" });
  }
  connectConnector(connector: ConnectorKind, workspaceId?: string | null): Promise<ConnectHandoff> {
    return this.request(this.scoped(`/v1/connectors/${connector}/connect`, workspaceId), { method: "POST" });
  }
  connectorAttempt(attemptId: string): Promise<ConnectionAttempt> { return this.request(`/v1/connector-attempts/${attemptId}`); }
  updateConnectorSettings(connector: ConnectorKind, autoFetchEnabled: boolean, intervalMinutes: number, workspaceId?: string | null): Promise<void> {
    return this.request(this.scoped(`/v1/connectors/${connector}/settings`, workspaceId), { method: "POST", body: JSON.stringify({ auto_fetch_enabled: autoFetchEnabled, interval_minutes: intervalMinutes }) });
  }
  syncConnector(connector: ConnectorKind, workspaceId?: string | null): Promise<ConnectorSnapshot> {
    return this.request(this.scoped(`/v1/connectors/${connector}/sync`, workspaceId), { method: "POST" });
  }
  disconnectConnector(connector: ConnectorKind, workspaceId?: string | null): Promise<void> {
    return this.request(this.scoped(`/v1/connectors/${connector}/disconnect`, workspaceId), { method: "POST", body: JSON.stringify({ confirm: true }) });
  }
  automations(workspaceId: string): Promise<Automation[]> {
    return this.request(this.scoped("/v1/automations", workspaceId));
  }
  createAutomation(input: { workspace_id: string; name: string; prompt: string; schedule: AutomationSchedule }): Promise<Automation> {
    return this.request("/v1/automations", { method: "POST", body: JSON.stringify(input) });
  }
  updateAutomation(automationId: string, input: { expected_version: number; name?: string; prompt?: string; schedule?: AutomationSchedule }): Promise<Automation> {
    return this.request(`/v1/automations/${encodeURIComponent(automationId)}`, { method: "PATCH", body: JSON.stringify(input) });
  }
  setAutomationStatus(automationId: string, operation: "pause" | "resume", version: number): Promise<Automation> {
    return this.request(`/v1/automations/${encodeURIComponent(automationId)}/${operation}`, { method: "POST", body: JSON.stringify({ expected_version: version }) });
  }
  runAutomation(automationId: string): Promise<AutomationRunLink> {
    return this.request(`/v1/automations/${encodeURIComponent(automationId)}/run`, { method: "POST" });
  }
  automationHistory(automationId: string): Promise<AutomationRunLink[]> {
    return this.request(`/v1/automations/${encodeURIComponent(automationId)}/history`);
  }
  deleteAutomation(automationId: string, version: number): Promise<void> {
    return this.request(`/v1/automations/${encodeURIComponent(automationId)}`, { method: "DELETE", body: JSON.stringify({ expected_version: version, confirm: true }) });
  }
  skills(workspaceId: string): Promise<SkillCatalogEntry[]> {
    return this.request(this.scoped("/v1/skills/catalog", workspaceId));
  }
  installSkill(skillId: string, workspaceId: string, workspaceVersion: number, clientRequestId: string): Promise<InstallApprovalRequest> {
    return this.request(`/v1/skills/${encodeURIComponent(skillId)}/install`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, expected_workspace_version: workspaceVersion, client_request_id: clientRequestId }) });
  }
  uninstallSkill(skillId: string, workspaceId: string, workspaceVersion: number): Promise<SkillCatalogEntry> {
    return this.request(`/v1/skills/${encodeURIComponent(skillId)}`, { method: "DELETE", body: JSON.stringify({ workspace_id: workspaceId, expected_workspace_version: workspaceVersion, confirm: true }) });
  }
  mcpPresets(workspaceId: string): Promise<MCPPreset[]> {
    return this.request(this.scoped("/v1/mcp/catalog", workspaceId));
  }
  installMCP(presetId: string, workspaceId: string, clientRequestId: string): Promise<InstallApprovalRequest> {
    return this.request(`/v1/mcp/${encodeURIComponent(presetId)}/install`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, client_request_id: clientRequestId }) });
  }
  setMCPEnabled(presetId: string, workspaceId: string, enabled: boolean): Promise<MCPPreset> {
    return this.request(`/v1/mcp/${encodeURIComponent(presetId)}/${enabled ? "enable" : "disable"}`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) });
  }

  events(cursor: string | null, onEvent: (event: LedgerEvent) => void, onRefresh: () => void, onDisconnect?: () => void): WebSocket {
    const url = new URL(this.config.baseUrl.replace(/^http/, "ws") + "/v1/events");
    if (cursor) url.searchParams.set("cursor", cursor);
    const protocols = this.config.token
      ? ["weatherflow-v1", `weatherflow-auth.${this.config.token}`]
      : undefined;
    const socket = new WebSocket(url, protocols);
    socket.onmessage = (message) => onEvent(JSON.parse(message.data as string) as LedgerEvent);
    socket.onclose = (event) => {
      if (event.code === 4409) onRefresh();
      onDisconnect?.();
    };
    return socket;
  }
}
