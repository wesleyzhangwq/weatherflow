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

// ----- Types mirror backend pydantic schemas -----
export type Weather =
  | "sunny"
  | "partly_cloudy"
  | "cloudy"
  | "rainy"
  | "thunderstorm"
  | "foggy";

export type CheckinFriction =
  | "task_complexity"
  | "missing_info"
  | "context_switch"
  | "external_block"
  | "energy"
  | "none";

export interface CheckinIn {
  weather: Weather;
  project?: string | null;
  friction_point?: CheckinFriction | null;
  free_text?: string | null;
}

export type HypothesisLabel =
  | "Flow"
  | "Recovery"
  | "Steady"
  | "Overload"
  | "Blocked"
  | "Fragmented";

export type SourceTag = "checkin" | "scheduled" | "chat" | "recalibrate";

export interface Evidence {
  text: string;
  source_event_id: string;
}

export interface HypothesisCard {
  id: string;
  timestamp: string;
  label: HypothesisLabel;
  confidence: number;
  summary: string;
  evidence: Evidence[];
  counter_evidence: Evidence[];
  missing_evidence: string[];
  source_tag: SourceTag;
  conversation_id?: string | null;
  status: "active" | "confirmed" | "rejected" | "partial" | "expired";
}

export interface CheckinResponse {
  checkin_id: string;
  hypothesis_id: string;
  hypothesis: HypothesisCard;
}

export interface ProposalCard {
  id: string;
  timestamp: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  rationale: string;
  conversation_id?: string | null;
  status: "pending" | "confirmed" | "rejected" | "expired";
}

export interface ProfileOut {
  path: string;
  markdown: string;
  sections: Record<string, string>;
}

export interface EventRecord {
  id: string;
  type: string;
  user_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
  refs: Record<string, unknown>;
}

export interface DashboardSnapshot {
  today_calendar: {
    event_count: number;
    total_minutes: number;
    next_event_summary: string | null;
    next_event_start: string | null;
    has_data: boolean;
  };
  this_week_github: {
    commits: number;
    open_prs: number;
    active_repos: string[];
    window_days: number;
    has_data: boolean;
  };
  scheduler: {
    last_check_at: string | null;
    last_check_minutes_ago: number | null;
    next_check_at: string | null;
    next_check_minutes: number | null;
  };
  pending_proposals_count: number;
  recent_rhythm: Array<{
    timestamp: string;
    label: HypothesisLabel;
    verdict: "confirmed" | "rejected" | "partial" | "pending";
  }>;
  profile: {
    active_projects_preview: string[];
    last_patch_at: string | null;
    last_patch_minutes_ago: number | null;
  };
  latest_hypothesis: {
    id: string;
    label: HypothesisLabel;
    confidence: number;
    summary: string;
    source_tag: SourceTag;
    timestamp: string;
    minutes_ago: number;
    status: "active" | "confirmed" | "rejected" | "partial" | "expired";
  } | null;
  latest_checkin: {
    id: string;
    weather: Weather;
    project: string | null;
    friction_point: CheckinFriction | null;
    free_text: string | null;
    timestamp: string;
    minutes_ago: number;
  } | null;
}

// ----- Endpoints -----
export const api = {
  hypotheses: (limit = 3) =>
    request<HypothesisCard[]>(`/api/hypotheses?limit=${limit}`),
  hypothesisHistory: (limit = 50) =>
    request<HypothesisCard[]>(`/api/hypotheses/history?limit=${limit}`),
  submitCheckin: (body: CheckinIn) =>
    request<CheckinResponse>("/api/checkin", {
      method: "POST",
      body: JSON.stringify(body)
    }),
  submitFeedback: (
    hypothesisId: string,
    verdict: "confirmed" | "rejected" | "partial"
  ) =>
    request<{ feedback_id: string; hypothesis_id: string; verdict: string }>(
      `/api/hypotheses/${hypothesisId}/feedback`,
      { method: "POST", body: JSON.stringify({ verdict }) }
    ),
  profile: () => request<ProfileOut>("/api/profile"),
  event: (eventId: string) =>
    request<EventRecord>(`/api/events/${encodeURIComponent(eventId)}`),
  proposals: (status?: string) =>
    request<ProposalCard[]>(
      "/api/actions/proposals" + (status ? `?status=${status}` : "")
    ),
  executeProposal: (proposalId: string) =>
    request<{ proposal_id: string; tool_name: string; result: unknown }>(
      `/api/actions/${encodeURIComponent(proposalId)}/execute`,
      { method: "POST", body: JSON.stringify({ confirmed: true }) }
    ),
  rejectProposal: (proposalId: string) =>
    request(`/api/actions/${encodeURIComponent(proposalId)}/reject`, {
      method: "POST",
      body: "{}"
    }),
  dashboardSnapshot: () => request<DashboardSnapshot>("/api/dashboard/snapshot"),
  chatHistory: (conversationId: string) =>
    request<Array<{ kind: string; timestamp: string; data: Record<string, unknown> }>>(
      `/api/chat/${encodeURIComponent(conversationId)}/history`
    ),
  conversations: () =>
    request<
      Array<{
        conversation_id: string;
        last_activity: string;
        first_user_message: string | null;
        turn_count: number;
      }>
    >("/api/chat/conversations")
};

// ----- Conversation id helper -----
export function newConversationId(): string {
  // ULID-ish (not RFC-strict; backend treats as opaque per ADR D5)
  const t = Date.now().toString(36);
  const r = Math.random().toString(36).slice(2, 10);
  return `conv_${t}_${r}`;
}
