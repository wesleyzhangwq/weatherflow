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

export type CostBudgetStatus = "unlimited" | "pending_usage" | "within_budget" | "exceeded" | "unknown_cost";
export type CostFailureReason = "cost_unknown" | "cost_budget_exhausted";
export type BillingOrigin =
  | "minimax_global_paygo"
  | "minimax_cn_paygo"
  | "minimax_global_token_plan"
  | "minimax_cn_token_plan";

export interface RunUsage {
  schema_version: "run_usage_v1";
  run_id: string;
  provider: string | null;
  model: string | null;
  input_tokens: number;
  cache_read_input_tokens: number | null;
  output_tokens: number;
  total_tokens: number;
  cost_amount: number | null;
  cost_usd: number | null;
  currency: "USD" | "CNY" | null;
  cost_scope: "model_usage_only";
  billing_origin: BillingOrigin | null;
  cost_status: "known" | "unknown";
  pricing_catalog_version: string | null;
  step_count: number;
  elapsed_seconds: number;
  timeout_seconds: number;
  max_cost_usd: number | null;
  cost_budget_usage_percent: number | null;
  cost_budget_status: CostBudgetStatus;
  cost_failure_reason: CostFailureReason | null;
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
}

export type ActivityAfkState = "active" | "afk" | "unknown";
export type ActivitySummaryKind = "stage_6h" | "daily_24h" | "weekly" | "biweekly" | "monthly";
export type ActivitySummaryFinality = "provisional" | "final";
export type ActivitySummaryTaskStatus = "pending" | "running" | "completed" | "failed" | "needs_retry";

export interface ActivityEvidenceRef {
  activitywatch_server_id?: string;
  bucket_id: string;
  event_id: string;
  event_timestamp?: string;
  event_duration?: number;
  event_digest?: string;
  fields_used?: string[];
}

export interface ActivityWatchSourceStatus {
  reachable: boolean;
  server_version: string | null;
  data_start: string | null;
  data_end: string | null;
  checked_at: string;
  last_reconciled_at: string | null;
  error_code: string | null;
}

export interface ActivityObservedFact {
  observed_at: string;
  started_at: string;
  duration_seconds: number;
  app_name: string | null;
  window_title: string | null;
  url: string | null;
  afk_state: ActivityAfkState;
  evidence_refs: ActivityEvidenceRef[];
}

export interface WatchCurrent {
  observed: ActivityObservedFact | null;
  afk_state: ActivityAfkState;
  observed_at: string;
  source_health: "available" | "degraded";
}

export interface ActivityStatistics {
  window_start: string;
  window_end: string;
  active_seconds: number;
  afk_seconds: number;
  app_switch_count: number;
  category_switch_count: number;
  app_seconds: Record<string, number>;
  category_seconds: Record<string, number>;
  category_rule_version: string;
  observed_seconds: number;
  unobserved_seconds: number;
  window_observed_seconds: number;
  afk_observed_seconds: number;
  web_observed_seconds: number;
  coverage_ratio: number;
  coverage_status: "none" | "partial" | "complete";
  source_bucket_ids: string[];
}

export interface ActivityTimelineEntry {
  id: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  app_name: string | null;
  category: string | null;
  afk_state: ActivityAfkState;
  window_title?: string | null;
  url?: string | null;
  evidence_refs?: ActivityEvidenceRef[];
}

export interface ActivityWatchDashboard {
  statistics: ActivityStatistics;
  timeline: ActivityTimelineEntry[];
}

export interface ActivitySummaryRecord {
  id: string;
  task_id: string;
  kind: ActivitySummaryKind;
  finality: ActivitySummaryFinality;
  timezone: "Asia/Shanghai";
  window_start: string;
  window_end: string;
  statistics: ActivityStatistics;
  narrative: string;
  evidence_refs: ActivityEvidenceRef[];
  connector_evidence_refs: Array<{
    connector: "github" | "gmail" | "google_calendar";
    source_id_digest: string;
    occurred_at: string;
    ends_at: string | null;
    item_digest: string;
    snapshot_fetched_at: string;
  }>;
  connector_coverage: Array<{
    connector: "github" | "gmail" | "google_calendar";
    health:
      | "healthy"
      | "degraded"
      | "requires_reconnect"
      | "disabled"
      | "unavailable"
      | "stale";
    connected: boolean;
    enabled: boolean;
    stale: boolean;
    snapshot_fetched_at: string | null;
    window_item_count: number;
    snapshot_watermark: string;
  }>;
  category_rule_version: string;
  rules_stale: boolean;
  provider?: string | null;
  model_version: string | null;
  requested_provider?: string | null;
  requested_model?: string | null;
  fallback_reason?: string | null;
  prompt_version: string;
  completed_at: string;
  attempt_count?: number;
  source_watermark?: string | null;
}

export interface ActivitySummaryTask {
  id: string;
  kind: ActivitySummaryKind;
  window_start: string;
  window_end: string;
  status: ActivitySummaryTaskStatus;
  attempt_count: number;
  completed_at: string | null;
  next_attempt_at: string | null;
  error_code: string | null;
  finality?: ActivitySummaryFinality | null;
}

export interface ActivitySummarySettings {
  model_workspace_id: string;
  provider: string | null;
  model: string | null;
  model_configuration_version: number | null;
  prompt_version: string;
  version: number;
  updated_at: string;
}

export interface ActivitySummarySettingsUpdate {
  model_workspace_id: string;
  model: string;
  expected_version: number;
}

export interface ActivityTrendPoint {
  window_start: string;
  window_end: string;
  active_seconds: number;
  afk_seconds: number;
  app_switch_count: number;
  dominant_category: string | null;
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
  behavior_sensor: { mode: "activitywatch_read_only"; raw_content_captured: false; fallback_to_deliberate_signals: true };
  retention: Record<string, string>;
  model: { configured: boolean; provider: string; model: string | null; base_url: string | null; billing_origin?: BillingOrigin | null; credential_available: boolean };
}
export interface ModelProviderPreset {
  provider: string;
  label: string;
  base_url: string;
  default_model: string;
  suggested_models: string[];
  billing_origins?: BillingOrigin[];
}
export interface ProviderModel {
  id: string;
  selectable: boolean;
  compatibility: "agent_ready" | "requires_hidden_reasoning";
  note: string | null;
}
export interface ProviderModelCatalog { provider: string; models: ProviderModel[]; source: "provider" }
export interface ModelConfigureInput { provider: string; model: string; base_url: string; billing_origin?: BillingOrigin | null }
export interface ModelConfigurationResponse { configuration: { workspace_id: string; provider: string; model: string; base_url: string; billing_origin?: BillingOrigin | null }; status: SystemStatus["model"] }
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
export interface ConnectorSourceItem { source_id: string; occurred_at: string; ends_at?: string | null; title: string; summary: string; url: string | null; untrusted?: true }
export interface ConnectorSnapshot { workspace_id: string; connector: ConnectorKind; fetched_at: string; expires_at: string; items: ConnectorSourceItem[] }
export type WatchOAuthSourceHealth = "healthy" | "degraded" | "requires_reconnect" | "disabled" | "unavailable" | "stale";
export type WatchOAuthRefreshCadence = "daily";
export type WatchOAuthFetchStrategy =
  | "github_unread_notifications_and_recent_activity"
  | "gmail_unread_metadata_30d"
  | "google_calendar_all_calendars_past_7d_future_14d";
export type WatchOAuthNormalizationHealth = "unknown" | "healthy" | "partial" | "failed";
export interface WatchOAuthFeedSource {
  connector: "github" | "gmail" | "google_calendar";
  label: string;
  health: WatchOAuthSourceHealth;
  connected: boolean;
  enabled: boolean;
  stale: boolean;
  item_count: number;
  last_sync_at: string | null;
  next_sync_at: string | null;
  snapshot_fetched_at: string | null;
  refresh_cadence: WatchOAuthRefreshCadence;
  fetch_strategy: WatchOAuthFetchStrategy;
  coverage_past_days: number;
  coverage_future_days: number;
  raw_item_count: number | null;
  normalized_item_count: number | null;
  normalization_health: WatchOAuthNormalizationHealth;
  last_error_code: string | null;
}
export interface WatchOAuthFeedItem extends ConnectorSourceItem {
  connector: "github" | "gmail" | "google_calendar";
  untrusted: true;
}
export interface WatchOAuthFeed {
  workspace_id: string;
  generated_at: string;
  sources: WatchOAuthFeedSource[];
  items: WatchOAuthFeedItem[];
}

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
