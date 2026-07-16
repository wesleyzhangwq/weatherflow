export type WeatherScene = "clear" | "fair" | "fog" | "storm" | "still" | "night" | "mixed";
export type RunStatus =
  | "queued" | "planning" | "running" | "waiting_approval" | "waiting_user"
  | "paused" | "needs_review" | "succeeded" | "failed" | "cancelled";
export type ToolMode = "ask" | "bypass";

export interface WeatherPresentation {
  scene: WeatherScene;
  intensity: number;
  transition: "steady" | "building" | "easing";
  snapshot_id: string;
  valid_until: string;
  presentation_version: string;
}

export interface CurrentRhythm {
  snapshot: {
    id: string;
    summary: string;
    valid_until: string;
    observed_at?: string;
    freshness?: "fresh" | "aging" | "expired";
    dimensions?: Partial<Record<RhythmDimensionName, RhythmDimensionEstimate>>;
  };
  policy: { proactivity: "silent"; work_mode: string };
  weather: WeatherPresentation;
}

export type RhythmDimensionName = "energy" | "cognitive_load" | "fragmentation" | "momentum" | "friction" | "recovery_need";
export interface RhythmDimensionEstimate {
  value: number;
  confidence: number;
  trend: "rising" | "steady" | "falling";
  freshness: "fresh" | "aging" | "expired";
}
export interface RecentBehaviorInsight {
  id: string;
  kind: "activity" | "task";
  observed_at: string;
  active_minutes: number | null;
  idle_minutes: number | null;
  app_switch_count: number | null;
  dominant_category: "development" | "communication" | "research" | "planning" | "creative" | "other" | null;
  outcome: "succeeded" | "failed" | "needs_review" | null;
  duration_minutes: number | null;
  step_count: number | null;
}
export interface ProfileInsight {
  id: string;
  claim: string;
  confidence: number;
  origin: "user" | "agent" | "derived";
  evidence_count: number;
  updated_at: string;
}
export interface RhythmInsights {
  current: CurrentRhythm;
  recent_behaviors: RecentBehaviorInsight[];
  profile: ProfileInsight[];
}

export interface Run {
  id: string;
  workspace_id: string;
  session_id?: string | null;
  tool_mode?: ToolMode;
  user_intent: string;
  status: RunStatus;
  result_summary: string | null;
  error_class?: string | null;
  error_message?: string | null;
  updated_at: string;
}

export interface Session {
  id: string;
  workspace_id: string;
  title: string;
  pinned: boolean;
  latest_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  action_roots: string[];
  installed_packs: string[];
  installed_skills?: string[];
  version?: number;
}

export interface DesktopSnapshot {
  rhythm: CurrentRhythm;
  latest_run: Run | null;
  workspace: Workspace;
  metadata_sensor_enabled: boolean;
}
export interface ActivityPreferences {
  collection_enabled: boolean;
  macos_enabled: boolean;
  browser_enabled: boolean;
  incognito_enabled: boolean;
  remote_inference_enabled: boolean;
  model_workspace_id: string | null;
  retention_days: 30 | 90 | 365 | null;
  version: number;
}
export interface ActivityHeartbeat {
  source: "macos_window" | "browser_tab" | "idle";
  device_id: string;
  source_instance: string;
  source_event_id: string;
  observed_at: string;
  pulsetime_seconds: number;
  app_name?: string | null;
  bundle_id?: string | null;
  window_title?: string | null;
  browser_name?: string | null;
  browser_window_id?: string | null;
  browser_tab_id?: string | null;
  url?: string | null;
  domain?: string | null;
  tab_title?: string | null;
  audible?: boolean | null;
  incognito?: boolean | null;
  focused?: boolean | null;
  idle_state: "active" | "idle" | "unknown";
  category?: string | null;
}
export interface ActivityInterval {
  id: string;
  source: "macos_window" | "browser_tab" | "idle";
  device_id: string;
  source_instance: string;
  source_event_id: string;
  started_at: string;
  ended_at: string;
  observed_at: string;
  duration_seconds: number;
  app_name: string | null;
  bundle_id: string | null;
  window_title: string | null;
  browser_name: string | null;
  browser_window_id: string | null;
  browser_tab_id: string | null;
  url: string | null;
  domain: string | null;
  tab_title: string | null;
  audible: boolean | null;
  incognito: boolean | null;
  focused: boolean | null;
  idle_state: "active" | "idle" | "unknown";
  category: string | null;
}
export interface ActivityRankItem { name: string; seconds: number }
export interface ActivitySummary {
  window_start: string;
  window_end: string;
  screen_seconds: number;
  browser_seconds: number;
  idle_seconds: number;
  current_streak_seconds: number;
  app_switch_count: number;
  tab_switch_count: number;
  category_seconds: Record<string, number>;
  top_apps: ActivityRankItem[];
  top_domains: ActivityRankItem[];
}
export interface ActivityInferenceJob {
  id: string;
  scheduled_for: string;
  window_start: string;
  window_end: string;
  workspace_id: string;
  status: "pending" | "executing" | "completed" | "failed" | "needs_review";
  provider: string | null;
  model: string | null;
  base_url: string | null;
  configuration_version: number | null;
  event_ids: string[];
  event_count: number;
  chunk_count: number;
  redaction_count: number;
  request_payload: string | null;
  response_payload: string | null;
  error_code: string | null;
  snapshot: CurrentRhythm["snapshot"] | null;
  created_at: string;
  updated_at: string;
}
export interface ActivityExport {
  exported_at: string;
  preferences: ActivityPreferences;
  events: ActivityInterval[];
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
export interface InstallApprovalRequest {
  status: "needs_approval";
  action_id: string;
  approval_id: string;
  approval_version: number;
  run_id: string;
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
export type ConnectorKind =
  | "github" | "gmail" | "google_calendar" | "slack" | "notion"
  | "google_drive" | "google_sheets" | "outlook" | "one_drive"
  | "microsoft_teams" | "linear" | "jira" | "confluence" | "dropbox"
  | "gitlab" | "discord" | "trello" | "asana" | "airtable" | "clickup";
export type ConnectionPhase = "waiting_user" | "active" | "expired" | "error" | "revoked";
export type OAuthSetup = "managed" | "bring_your_own" | "unknown";
export interface ConnectorStatus {
  connector: ConnectorKind;
  label: string;
  category: string;
  toolkit: string;
  oauth_setup: OAuthSetup;
  phase: ConnectionPhase | null;
  configured: boolean;
  connected: boolean;
  display_name: string | null;
  auto_fetch_supported: boolean;
  conversation_tools_supported: boolean;
  auto_fetch_enabled: boolean;
  interval_minutes: number;
  last_sync_at: string | null;
  next_sync_at: string | null;
  last_error_code: string | null;
  attempt_id: string | null;
  attempt_expires_at: string | null;
  available_tool_ids: string[];
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

export type AutomationStatus = "enabled" | "paused";
export type ScheduleKind = "once" | "hourly" | "daily" | "weekdays" | "weekly";
export interface AutomationSchedule {
  kind: ScheduleKind;
  timezone: string;
  once_at?: string | null;
  minute?: number | null;
  at_time?: string | null;
  weekday?: number | null;
}
export interface Automation {
  id: string;
  workspace_id: string;
  name: string;
  prompt: string;
  schedule: AutomationSchedule;
  status: AutomationStatus;
  next_run_at: string | null;
  last_run_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}
export interface AutomationRunLink {
  id: string;
  automation_id: string;
  workspace_id: string;
  trigger: "scheduled" | "manual";
  scheduled_for: string;
  client_request_id: string;
  status: "pending" | "submitted" | "failed";
  run_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}
export interface SkillCatalogEntry {
  id: string;
  name: string;
  description: string;
  description_zh: string | null;
  boundary_zh: string | null;
  category: string | null;
  license: string | null;
  related: string[];
  reads: string[];
  source: "wesley-skills";
  source_path: string;
  source_digest: string;
  validation_status: "valid" | "invalid";
  validation_errors: string[];
  installed: boolean;
  installed_reference: string | null;
}
export interface MCPPreset {
  preset_id: string;
  title: string;
  description: string;
  publisher: string;
  source_url: string;
  version: string;
  capabilities: string[];
  risk_note: string;
  available: boolean;
  unavailable_reason: string | null;
  installed: boolean;
  enabled: boolean;
  health: "not_installed" | "disabled" | "healthy" | "unavailable";
  tool_ids: string[];
  installed_at: string | null;
  checked_at: string | null;
}
