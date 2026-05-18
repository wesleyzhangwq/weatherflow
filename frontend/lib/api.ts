const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";

const SERVER_API_BASE = process.env.NEXT_SERVER_API_BASE || PUBLIC_API_BASE;

export const API_BASE =
  typeof window === "undefined" ? SERVER_API_BASE : PUBLIC_API_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store"
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---- Types (mirror of backend pydantic models) ----
export type WeatherLabel =
  | "Momentum"
  | "Confusion"
  | "Burnout"
  | "Overload"
  | "Recovery";

export interface UserState {
  focus: number;
  stress: number;
  burnout: number;
  momentum: number;
  confidence: number;
  motivation: number;
  weather_label: WeatherLabel;
  rationale?: string | null;
  ts?: string | null;
}

export interface StateTrendPoint {
  ts: string;
  focus: number;
  stress: number;
  burnout: number;
  momentum: number;
  confidence: number;
  motivation: number;
  weather_label: WeatherLabel;
}

export interface Reflection {
  id: number;
  date: string;
  kind: "daily" | "weekly";
  content: string;
  insights?: ReflectionInsights | null;
  created_at: string;
}

export type GroundingSourceType =
  | "checkin"
  | "state"
  | "git"
  | "notes"
  | "workspace"
  | "patterns"
  | "memory";

export interface GroundingSource {
  type: GroundingSourceType;
  label: string;
  summary: string;
}

export interface ReflectionInsights {
  weather_label?: WeatherLabel | null;
  checkins_considered?: number;
  git_records_considered?: number;
  suggestion?: string;
  grounding_sources?: GroundingSource[];
}

export interface CheckinIn {
  status?: string | null;
  did_today?: string | null;
  stuck_on?: string | null;
  anxiety?: string | null;
  raw?: string | null;
}

export interface PatternMetric {
  name: string;
  current: number;
  previous: number;
  delta: number;
  pct_delta: number | null;
}

export interface PatternHit {
  code: string;
  severity: "info" | "watch" | "alert";
  label: string;
  explanation: string;
  evidence: Record<string, unknown>;
}

export interface PatternReport {
  window_days: number;
  metrics: PatternMetric[];
  patterns: PatternHit[];
}

export interface CheckinResponse {
  checkin: CheckinIn & { id: number; date: string; created_at: string };
  state: UserState;
  reflection: Reflection;
  suggestion: string;
  patterns: PatternHit[];
  suggestion_pattern_codes: string[];
  pattern_window_days: number;
  pending_hypotheses: SensorHypothesis[];
}

export type HypothesisSourceType = "git" | "notes" | "workspace" | "patterns";
export type HypothesisStatus = "pending" | "confirmed" | "rejected" | "superseded";
export type HypothesisFeedback = "accurate" | "unsure" | "inaccurate";

export interface SensorHypothesis {
  id: number;
  created_at: string;
  last_seen_at: string;
  source_type: HypothesisSourceType;
  source_record_id?: number | null;
  key: string;
  label: string;
  summary: string;
  evidence?: Record<string, unknown> | null;
  confidence: number;
  seen_count: number;
  status: HypothesisStatus;
  user_feedback?: string | null;
  user_rating?: HypothesisFeedback | null;
  confirmed_at?: string | null;
  rejected_at?: string | null;
  rated_at?: string | null;
}

export interface SuggestionFeedbackIn {
  helpful: boolean;
  suggestion_text?: string;
  pattern_codes?: string[];
  reflection_id?: number;
  session_id?: string;
  note?: string | null;
}

export type MemoryFeedbackType =
  | "accurate"
  | "inaccurate"
  | "stale"
  | "important";

export interface MemoryFeedbackIn {
  semantic_key: string;
  feedback_type: MemoryFeedbackType;
  semantic_value_snapshot?: string;
  session_id?: string;
}

export interface ProfileOut {
  markdown: string;
  path: string;
}

export type DevWeather =
  | "Deep Work"
  | "Shipping"
  | "Collaboration Heavy"
  | "Fragmented"
  | "Blocked";

export interface AgentRunStep {
  name: string;
  status: "success" | "partial" | "failed" | "skipped";
  summary: string;
  metadata: Record<string, unknown>;
}

export interface AgentRunRecord {
  id: number;
  run_type: "dev_review";
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at?: string | null;
  input: Record<string, unknown>;
  steps: AgentRunStep[];
  error?: string | null;
}

export interface DevReview {
  id: number;
  run_id: number;
  window_days: number;
  summary: string;
  dev_weather: DevWeather;
  main_work_threads: string[];
  shipping_progress: string[];
  collaboration_load: string[];
  meeting_load: string[];
  rhythm_risks: string[];
  next_week_suggestion: string;
  source_coverage: Record<string, unknown>;
  created_at: string;
  run: AgentRunRecord;
}

// ---- Endpoints ----
export const api = {
  currentState: () => request<UserState>("/api/state/current"),
  stateTrend: (days = 14) =>
    request<StateTrendPoint[]>(`/api/state/trend?days=${days}`),
  patterns: (window = 7) =>
    request<PatternReport>(`/api/state/patterns?window_days=${window}`),
  reflections: (limit = 5) =>
    request<Reflection[]>(`/api/reflection?limit=${limit}`),
  runReflection: (kind: "daily" | "weekly" = "daily") =>
    request<Reflection>(`/api/reflection/run?kind=${kind}`, { method: "POST" }),
  submitCheckin: (body: CheckinIn) =>
    request<CheckinResponse>("/api/checkin", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  submitSuggestionFeedback: (body: SuggestionFeedbackIn) =>
    request<{ status: string }>("/api/feedback/suggestion", {
      method: "POST",
      body: JSON.stringify({
        helpful: body.helpful,
        suggestion_text: body.suggestion_text ?? "",
        pattern_codes: body.pattern_codes ?? [],
        reflection_id: body.reflection_id ?? null,
        session_id: body.session_id ?? "default",
        note: body.note ?? null
      })
    }),
  submitMemoryFeedback: (body: MemoryFeedbackIn) =>
    request<{ status: string }>("/api/feedback/memory", {
      method: "POST",
      body: JSON.stringify({
        semantic_key: body.semantic_key,
        feedback_type: body.feedback_type,
        semantic_value_snapshot: body.semantic_value_snapshot ?? "",
        session_id: body.session_id ?? "default"
      })
    }),
  submitHypothesisFeedback: (id: number, feedback: HypothesisFeedback) =>
    request<SensorHypothesis>(`/api/sensors/hypotheses/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback })
    }),
  profile: () => request<ProfileOut>("/api/memory/profile"),
  latestDevReview: () =>
    request<DevReview | null>("/api/dev-review/runs/latest"),
  runDevReview: (windowDays = 7) =>
    request<DevReview>("/api/dev-review/runs", {
      method: "POST",
      body: JSON.stringify({ window_days: windowDays })
    })
};
