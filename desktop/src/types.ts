export type WeatherScene = "clear" | "fair" | "fog" | "storm" | "still" | "night" | "mixed";
export type RunStatus =
  | "queued" | "planning" | "running" | "waiting_approval" | "waiting_user"
  | "paused" | "needs_review" | "succeeded" | "failed" | "cancelled";

export interface WeatherPresentation {
  scene: WeatherScene;
  intensity: number;
  transition: "steady" | "building" | "easing";
  snapshot_id: string;
  valid_until: string;
  presentation_version: string;
}

export interface CurrentRhythm {
  snapshot: { id: string; summary: string; valid_until: string };
  policy: { proactivity: "silent"; work_mode: string };
  weather: WeatherPresentation;
}

export interface Run {
  id: string;
  workspace_id: string;
  user_intent: string;
  status: RunStatus;
  result_summary: string | null;
  error_class?: string | null;
  error_message?: string | null;
  updated_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  action_roots: string[];
  installed_packs: string[];
}

export interface DesktopSnapshot {
  rhythm: CurrentRhythm;
  latest_run: Run | null;
  workspace: Workspace;
  metadata_sensor_enabled: boolean;
}
export interface Approval {
  id: string;
  action_id: string;
  run_id: string;
  status: string;
  version: number;
  tool_id: string;
  effect: string;
  preview: Record<string, unknown>;
}
export interface LedgerEvent { id: string; type: string; recorded_at: string; payload: Record<string, unknown> }
export interface Artifact { id: string; run_id: string; name: string; media_type: string; digest: string; size_bytes: number }
export interface SystemStatus {
  local_only: true;
  telemetry_upload: false;
  onboarding_completed: boolean;
  workspace_id: string;
  installed_packs: string[];
  providers: Record<string, string>;
  behavior_sensor: { mode: string; enabled?: boolean; raw_content_captured: false; fallback_to_deliberate_signals: true };
  retention: Record<string, string>;
  model: { configured: boolean; provider: string; model: string | null; base_url: string | null; credential_available: boolean };
}
export interface ModelProviderPreset {
  provider: string;
  label: string;
  base_url: string;
  default_model: string;
  suggested_models: string[];
}
export interface ProviderModel {
  id: string;
  selectable: boolean;
  compatibility: "agent_ready" | "requires_hidden_reasoning";
  note: string | null;
}
export interface ProviderModelCatalog { provider: string; models: ProviderModel[]; source: "provider" }
export interface ModelConfigureInput { provider: string; model: string; base_url: string }
export interface ModelConfigurationResponse { configuration: { workspace_id: string; provider: string; model: string; base_url: string }; status: SystemStatus["model"] }
export interface ResetPreview { category: string; count: number }
export interface ResetResult { category: string; deleted_count: number }
export interface DiagnosticExport { path: string; sha256: string; size_bytes: number }
export type ConnectorKind = "github" | "gmail" | "google_calendar";
export type ConnectionPhase = "waiting_user" | "active" | "expired" | "error" | "revoked";
export interface ConnectorStatus {
  connector: ConnectorKind;
  label: string;
  phase: ConnectionPhase | null;
  configured: boolean;
  connected: boolean;
  display_name: string | null;
  auto_fetch_enabled: boolean;
  interval_minutes: number;
  last_sync_at: string | null;
  next_sync_at: string | null;
  last_error_code: string | null;
  attempt_id: string | null;
  attempt_expires_at: string | null;
}
export interface ConnectHandoff { attempt_id: string; connect_url: string; expires_at: string }
export interface ConnectionAttempt {
  id: string;
  workspace_id: string;
  connector: ConnectorKind;
  account_id: string;
  external_account_id: string;
  phase: ConnectionPhase;
  expires_at: string;
  created_at: string;
  updated_at: string;
}
export interface ConnectorSourceItem { source_id: string; occurred_at: string; title: string; summary: string; url: string | null }
export interface ConnectorSnapshot { workspace_id: string; connector: ConnectorKind; fetched_at: string; expires_at: string; items: ConnectorSourceItem[] }
