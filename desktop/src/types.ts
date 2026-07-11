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
export interface Approval { id: string; action_id: string; run_id: string; status: string; version: number }
export interface LedgerEvent { id: string; type: string; recorded_at: string; payload: Record<string, unknown> }
export interface Artifact { id: string; run_id: string; name: string; media_type: string; digest: string; size_bytes: number }
