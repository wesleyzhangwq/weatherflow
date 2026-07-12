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
  user_intent: string;
  status: RunStatus;
  result_summary: string | null;
  updated_at: string;
}

export interface DesktopSnapshot { rhythm: CurrentRhythm; latest_run: Run | null }
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
  behavior_sensor: { mode: string; raw_content_captured: false; fallback_to_deliberate_signals: true };
  retention: Record<string, string>;
  model: { configured: boolean; provider: string; model: string | null; base_url: string | null; credential_available: boolean };
}
export interface ResetPreview { category: string; count: number }
export interface ResetResult { category: string; deleted_count: number }
export interface DiagnosticExport { path: string; sha256: string; size_bytes: number }
