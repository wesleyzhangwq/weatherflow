"""Pydantic schemas for L1 events, Hypothesis payloads, and EvidenceBundle.

Hard contracts come from weatherflow-architecture-v1.md §4.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Enums (v1 fixed — see ADR D13)
# ---------------------------------------------------------------------------
EventType = Literal[
    "checkin",
    "calendar_snapshot",
    "github_snapshot",
    "evidence_summary",
    "hypothesis",
    "hypothesis_feedback",
    "chat_turn",
    "reasoning_step",
    "tool_call",
    "proposal",
    "executed_action",
    "proposal_rejected",
    "proposal_expired",
    "profile_patch",
    "hypothesis_generation_error",
]

HypothesisLabel = Literal[
    "Flow",
    "Recovery",
    "Steady",
    "Overload",
    "Blocked",
    "Fragmented",
]

SourceTag = Literal["checkin", "scheduled", "chat", "recalibrate"]

Weather = Literal[
    "sunny",          # 晴天   — 清醒高效   → label 默认 Flow
    "partly_cloudy",  # 多云   — 能工作但不锋利 → Steady
    "cloudy",         # 阴天   — 低能量拖延   → Recovery
    "rainy",          # 小雨   — 情绪干扰中   → Overload
    "thunderstorm",   # 雷暴   — 混乱过载     → Blocked
    "foggy",          # 大雾   — 思路碎片化   → Fragmented
]
# 6 weathers ↔ 6 labels (ADR-002). The mapping is a "default suggestion" to
# the LLM, not a hard rule — evidence can override the user's self-report.

CheckinFriction = Literal[
    "task_complexity",
    "missing_info",
    "context_switch",
    "external_block",
    "energy",
    "none",
]

FeedbackVerdict = Literal["confirmed", "rejected", "partial"]

ProposalStatus = Literal["pending", "confirmed", "rejected", "expired"]

ToolMode = Literal["read", "write", "destructive"]

ProfileSection = Literal[
    "Identity",
    "Active Projects",
    "Rhythm Patterns",
    "Preferences",
    "Anti-patterns",
    "Recent Themes",
]


# ---------------------------------------------------------------------------
# L1 EventRecord (read-side projection)
# ---------------------------------------------------------------------------
class EventRecord(BaseModel):
    id: str
    type: EventType
    user_id: str
    timestamp: str  # ISO-8601 UTC
    payload: Dict[str, Any]
    refs: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Check-in payload (T1) — see §2 T1
# ---------------------------------------------------------------------------
class CheckinPayload(BaseModel):
    weather: Weather
    project: Optional[str] = None
    friction_point: Optional[CheckinFriction] = None
    free_text: Optional[str] = None


# ---------------------------------------------------------------------------
# Hypothesis payload — see §4.2 (hard contract)
# ---------------------------------------------------------------------------
class EvidenceItem(BaseModel):
    text: str
    source_event_id: str  # MUST exist in bundle


class HypothesisPayload(BaseModel):
    label: HypothesisLabel
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    counter_evidence: List[EvidenceItem] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    source_tag: SourceTag
    conversation_id: Optional[str] = None  # set when source_tag == "chat"

    @model_validator(mode="after")
    def _evidence_non_empty(self) -> "HypothesisPayload":
        # At minimum, must reference the trigger event — bundle.load() always
        # includes it, so an empty evidence array means the LLM cheaped out.
        if not self.evidence:
            raise ValueError("Hypothesis must include at least one evidence item.")
        return self


# ---------------------------------------------------------------------------
# Hypothesis feedback (T3) — see §5.3
# ---------------------------------------------------------------------------
class HypothesisFeedbackPayload(BaseModel):
    hypothesis_id: str
    verdict: FeedbackVerdict


# ---------------------------------------------------------------------------
# Calendar / GitHub raw snapshots — see §8.2 / §4.1 table
# ---------------------------------------------------------------------------
class CalendarSnapshotPayload(BaseModel):
    events: List[Dict[str, Any]] = Field(default_factory=list)
    window_start: str  # ISO
    window_end: str  # ISO
    calendar_id: str = "primary"


class GithubSnapshotPayload(BaseModel):
    commits: List[Dict[str, Any]] = Field(default_factory=list)
    prs: List[Dict[str, Any]] = Field(default_factory=list)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    active_repos: List[str] = Field(default_factory=list)
    window_days: int = 7


class EvidenceSummaryPayload(BaseModel):
    text: str
    headline_metrics: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Chat / Tool / Proposal events — see §4.1 / §7
# ---------------------------------------------------------------------------
class ChatTurnPayload(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    conversation_id: str


class ReasoningStepPayload(BaseModel):
    text: str
    conversation_id: str


class ToolCallPayload(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    conversation_id: str


class ProposalPayload(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    rationale: str
    status: ProposalStatus = "pending"
    conversation_id: str


class ExecutedActionPayload(BaseModel):
    proposal_id: str
    tool_name: str
    result: Any = None


class ProfilePatchPayload(BaseModel):
    section: ProfileSection
    diff: str
    confidence: float
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# EvidenceBundle (L2 — not persisted)
# ---------------------------------------------------------------------------
class BundleEntry(BaseModel):
    event_id: str
    # L2 working-context label, not an L1 event: usually an EventType, but also
    # "semantic_recall" for L2.5/mem0 hits. Kept as str so the bundle can carry
    # derived entry kinds without widening the L1 EventType invariant.
    event_type: str
    rendered: str  # the chunk the LLM will see


class EvidenceBundle(BaseModel):
    trigger_event_id: str
    entries: List[BundleEntry] = Field(default_factory=list)
    profile_sections: Dict[ProfileSection, str] = Field(default_factory=dict)
    # L3-fast: consolidated profile traits from mem0 infer=True (ADR-006). These
    # are synthesized facts with no single source event, so they live here —
    # NOT in `entries` — and are therefore exempt from the critic's
    # source_event_id check (`all_event_ids` only reads `entries`).
    live_insights: List[str] = Field(default_factory=list)
    mode: Literal["checkin", "background", "chat"]
    total_chars: int = 0

    def all_event_ids(self) -> set[str]:
        return {e.event_id for e in self.entries}

    def render(self) -> str:
        """Serialize into the format LLM sees (see §4.3)."""
        lines: list[str] = ["=== Evidence Bundle ===", ""]
        for entry in self.entries:
            lines.append(f"[{entry.event_id}]  ({entry.event_type})")
            lines.append(entry.rendered.rstrip())
            lines.append("")
        if self.profile_sections:
            lines.append("=== Profile Sections ===")
            for section, text in self.profile_sections.items():
                lines.append(f"## {section}")
                lines.append(text.strip())
                lines.append("")
        if self.live_insights:
            lines.append("=== Live Insights (long-term, may be approximate) ===")
            for fact in self.live_insights:
                lines.append(f"- {fact.strip()}")
            lines.append("")
        lines.append("=== End of Bundle ===")
        return "\n".join(lines)
