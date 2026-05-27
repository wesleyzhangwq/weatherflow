"""ContextLoader — assembles the L2 EvidenceBundle.

See weatherflow-architecture-v1.md §6 for the full spec. Three things make
this module non-trivial:

1. It must ALWAYS include the trigger event (§6.1) so the LLM has something
   to anchor on, even on cold start.
2. The mode → profile-section mapping (§6.2) is strict — Rhythm Patterns are
   for checkin/background, Identity+Preferences are for chat.
3. Token budget (§6.3) is enforced by priority truncation, not by silently
   dropping high-value items.
"""

from __future__ import annotations

import json
from typing import Dict, List, Literal, Optional

from app.config import get_settings
from app.memory import event_log, profile_md
from app.memory.schemas import (
    BundleEntry,
    EventRecord,
    EvidenceBundle,
    ProfileSection,
)

Mode = Literal["checkin", "background", "chat"]


# §6.2 mode → profile sections
_MODE_TO_SECTIONS: Dict[Mode, List[ProfileSection]] = {
    "checkin": ["Rhythm Patterns", "Recent Themes", "Active Projects"],
    "background": ["Rhythm Patterns", "Anti-patterns", "Recent Themes"],
    "chat": ["Identity", "Preferences", "Rhythm Patterns", "Active Projects"],
}


# Rough char-to-token estimate. 1 token ~ 4 chars for English, ~2 for Chinese.
# We use 3 as a middle-ground conservative estimate.
def _est_tokens(s: str) -> int:
    return max(1, len(s) // 3)


async def load(
    *,
    trigger_event_id: str,
    mode: Mode,
    user_id: Optional[str] = None,
) -> EvidenceBundle:
    """Assemble an EvidenceBundle per §6.1.

    Order matters: trigger comes first, then high-value snapshots, then
    historical context, then profile sections.
    """
    uid = user_id or get_settings().default_user_id
    settings = get_settings()
    bundle = EvidenceBundle(trigger_event_id=trigger_event_id, mode=mode)

    trigger = event_log.get(trigger_event_id)
    if trigger is None:
        raise ValueError(f"trigger event not found: {trigger_event_id}")
    bundle.entries.append(_render_event(trigger, must_keep=True))

    seen: set[str] = {trigger.id}

    def _add(rec: EventRecord, *, must_keep: bool = False) -> None:
        if rec.id in seen:
            return
        seen.add(rec.id)
        bundle.entries.append(_render_event(rec, must_keep=must_keep))

    # §6.1 most-recent items by type
    for rec in event_log.latest_by_type(["hypothesis"], user_id=uid, limit=3):
        _add(rec)
    for rec in event_log.latest_by_type(["hypothesis_feedback"], user_id=uid, limit=5):
        _add(rec, must_keep=True)  # high signal, never truncate (§6.3)
    for rec in event_log.latest_by_type(["checkin"], user_id=uid, limit=3):
        _add(rec)

    cal = event_log.latest_one("calendar_snapshot", user_id=uid)
    if cal:
        _add(cal, must_keep=True)
    gh = event_log.latest_one("github_snapshot", user_id=uid)
    if gh:
        _add(gh, must_keep=True)
    summary = event_log.latest_one("evidence_summary", user_id=uid)
    if summary:
        _add(summary)

    # §6.2 profile sections per mode
    bundle.profile_sections = profile_md.read_sections(
        sections=_MODE_TO_SECTIONS[mode], user_id=uid
    )

    # §6.3 enforce token budget
    _enforce_budget(bundle, budget_tokens=settings.bundle_token_budget)

    bundle.total_chars = sum(len(e.rendered) for e in bundle.entries) + sum(
        len(v) for v in bundle.profile_sections.values()
    )
    return bundle


def _render_event(rec: EventRecord, *, must_keep: bool = False) -> BundleEntry:
    """Produce a compact text representation for the LLM."""
    rendered = _render_payload(rec)
    entry = BundleEntry(event_id=rec.id, event_type=rec.type, rendered=rendered)
    # Mark must-keep entries by prefix tag in `rendered` so _enforce_budget
    # can preserve them. Cheaper than a separate field, and the LLM doesn't
    # care about the suffix.
    if must_keep:
        entry.rendered = "★ " + entry.rendered
    return entry


def _render_payload(rec: EventRecord) -> str:
    p = rec.payload
    t = rec.type
    if t == "checkin":
        lines = [f"Check-in at {rec.timestamp}", f"  weather: {p.get('weather')}"]
        if p.get("project"):
            lines.append(f"  project: {p['project']}")
        if p.get("friction_point"):
            lines.append(f"  friction: {p['friction_point']}")
        if p.get("free_text"):
            lines.append(f"  notes: {p['free_text']}")
        return "\n".join(lines)
    if t == "calendar_snapshot":
        evs = p.get("events", [])
        sample = evs[:5]
        return (
            f"Calendar snapshot: {len(evs)} events between {p.get('window_start')} "
            f"and {p.get('window_end')}\n"
            + "\n".join(
                f"  - {e.get('start', '')} {e.get('summary') or e.get('title') or ''}"
                for e in sample
            )
        )
    if t == "github_snapshot":
        return (
            f"GitHub snapshot ({p.get('window_days', 7)}d): "
            f"{len(p.get('commits', []))} commits / {len(p.get('prs', []))} PRs / "
            f"{len(p.get('issues', []))} issues; "
            f"active repos: {', '.join(p.get('active_repos', []))}"
        )
    if t == "evidence_summary":
        text = p.get("text", "")
        metrics = p.get("headline_metrics", {})
        return f"Evidence summary:\n{text.strip()}\n  metrics: {json.dumps(metrics, ensure_ascii=False)}"
    if t == "hypothesis":
        return (
            f"Past hypothesis ({p.get('source_tag', '?')}): "
            f"{p.get('label')} @ conf {p.get('confidence'):.2f}\n  → {p.get('summary', '')}"
        )
    if t == "hypothesis_feedback":
        return f"User feedback on {p.get('hypothesis_id')}: {p.get('verdict')}"
    if t == "chat_turn":
        return f"Chat ({p.get('role')}): {p.get('content', '')[:200]}"
    return f"{t}: {json.dumps(p, ensure_ascii=False)[:300]}"


_BUDGET_TRUNCATABLE_PREFIXES: tuple[str, ...] = (
    "Past hypothesis",
    "Chat (",
)


def _enforce_budget(bundle: EvidenceBundle, *, budget_tokens: int) -> None:
    def total() -> int:
        return sum(_est_tokens(e.rendered) for e in bundle.entries) + sum(
            _est_tokens(v) for v in bundle.profile_sections.values()
        )

    if total() <= budget_tokens:
        return

    # §6.3 truncation priority — drop low-priority entries first.
    # Pass 1: truncate older "Past hypothesis" / "Chat" entries.
    for entry in list(reversed(bundle.entries)):
        if total() <= budget_tokens:
            return
        if entry.rendered.startswith("★ "):
            continue
        if any(entry.rendered.lstrip().startswith(p) for p in _BUDGET_TRUNCATABLE_PREFIXES):
            bundle.entries.remove(entry)

    # Pass 2: shrink profile sections (keep first paragraph).
    for section in list(bundle.profile_sections.keys()):
        if total() <= budget_tokens:
            return
        text = bundle.profile_sections[section]
        first_para = text.split("\n\n", 1)[0]
        if first_para != text:
            bundle.profile_sections[section] = first_para

    # Pass 3: as last resort, drop oldest non-starred entries.
    for entry in list(reversed(bundle.entries)):
        if total() <= budget_tokens:
            return
        if entry.rendered.startswith("★ ") or entry.event_id == bundle.trigger_event_id:
            continue
        bundle.entries.remove(entry)


__all__ = ["Mode", "load"]
