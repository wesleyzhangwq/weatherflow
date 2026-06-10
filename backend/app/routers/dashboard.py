"""Dashboard aggregation endpoint — fuels the main-page ambient widgets.

Returns small projections derived from L1 + profile.md + scheduler config.
NO new data collection — everything is computed on the fly from existing
events. Keep it cheap; the homepage polls this on every load.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings
from app.memory import event_log, profile_md

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# --------------------------------------------------------------------------- response model


class CalendarSummary(BaseModel):
    event_count: int = 0
    total_minutes: int = 0
    next_event_summary: Optional[str] = None
    next_event_start: Optional[str] = None
    has_data: bool = False


class GithubSummary(BaseModel):
    commits: int = 0
    open_prs: int = 0
    active_repos: List[str] = []
    window_days: int = 7
    has_data: bool = False


class SchedulerHeartbeat(BaseModel):
    last_check_at: Optional[str] = None
    last_check_minutes_ago: Optional[int] = None
    next_check_at: Optional[str] = None
    next_check_minutes: Optional[int] = None


class RhythmBeat(BaseModel):
    timestamp: str
    label: str
    verdict: str  # confirmed / rejected / partial / pending


class ProfileSnapshot(BaseModel):
    active_projects_preview: List[str] = []
    last_patch_at: Optional[str] = None
    last_patch_minutes_ago: Optional[int] = None


class LatestHypothesis(BaseModel):
    id: str
    label: str
    confidence: float
    summary: str
    source_tag: str
    timestamp: str
    minutes_ago: int
    status: str  # active / confirmed / rejected / partial / expired


class LatestCheckin(BaseModel):
    id: str
    weather: str
    project: Optional[str] = None
    friction_point: Optional[str] = None
    free_text: Optional[str] = None
    timestamp: str
    minutes_ago: int


class DashboardSnapshot(BaseModel):
    today_calendar: CalendarSummary
    this_week_github: GithubSummary
    scheduler: SchedulerHeartbeat
    pending_proposals_count: int
    recent_rhythm: List[RhythmBeat]
    profile: ProfileSnapshot
    latest_hypothesis: Optional[LatestHypothesis] = None
    latest_checkin: Optional[LatestCheckin] = None


# --------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _today_calendar() -> CalendarSummary:
    snap = event_log.latest_one("calendar_snapshot")
    if snap is None:
        return CalendarSummary()
    events = snap.payload.get("events") or []
    today = _now().date()

    todays: list[dict[str, Any]] = []
    for e in events:
        ts = _parse_ts(str(e.get("start") or ""))
        if ts and ts.date() == today:
            todays.append(e)

    upcoming = sorted(
        (e for e in events if (_parse_ts(str(e.get("start") or "")) or _now()) > _now()),
        key=lambda e: str(e.get("start") or ""),
    )
    next_evt = upcoming[0] if upcoming else None

    return CalendarSummary(
        event_count=len(todays),
        total_minutes=sum(int(e.get("duration_minutes") or 0) for e in todays),
        next_event_summary=(next_evt or {}).get("summary"),
        next_event_start=(next_evt or {}).get("start"),
        has_data=True,
    )


def _this_week_github() -> GithubSummary:
    snap = event_log.latest_one("github_snapshot")
    if snap is None:
        return GithubSummary()
    p = snap.payload
    return GithubSummary(
        commits=len(p.get("commits") or []),
        open_prs=len(p.get("prs") or []),
        active_repos=list(p.get("active_repos") or []),
        window_days=int(p.get("window_days") or 7),
        has_data=True,
    )


def _scheduler_heartbeat() -> SchedulerHeartbeat:
    s = get_settings()
    last_summary = event_log.latest_one("evidence_summary")
    last_at = last_summary.timestamp if last_summary else None
    last_minutes = None
    if last_at:
        ts = _parse_ts(last_at)
        if ts:
            last_minutes = int((_now() - ts).total_seconds() // 60)

    # next scheduled hour from the cron config
    hours = s.parsed_scheduled_check_hours or [0, 6, 12, 18]
    now_local = datetime.now()  # naive local
    today = now_local.date()
    candidates: list[datetime] = []
    for d in (0, 1):
        for h in hours:
            cand = datetime(today.year, today.month, today.day, h, 0) + timedelta(days=d)
            if cand > now_local:
                candidates.append(cand)
    next_dt = min(candidates) if candidates else None
    # next_dt is naive LOCAL time — attach the local offset (astimezone on a
    # naive datetime assumes local), not UTC, or the absolute timestamp is off
    # by the UTC offset for every non-UTC user.
    next_at = next_dt.astimezone().isoformat() if next_dt else None
    next_minutes = int((next_dt - now_local).total_seconds() // 60) if next_dt else None

    return SchedulerHeartbeat(
        last_check_at=last_at,
        last_check_minutes_ago=last_minutes,
        next_check_at=next_at,
        next_check_minutes=next_minutes,
    )


def _pending_proposals_count() -> int:
    """Reuse the lazy-expiry logic from actions router."""
    from app.routers.actions import _derived_status, _maybe_expire

    rows = event_log.list_recent(types=["proposal"], limit=100)
    count = 0
    for r in rows:
        st = _derived_status(r.id)
        if st == "pending":
            if not _maybe_expire(r.id, r.timestamp):
                count += 1
    return count


def _recent_rhythm(days: int = 7) -> List[RhythmBeat]:
    cutoff = _now() - timedelta(days=days)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    hyps = event_log.list_recent(types=["hypothesis"], since_ts=cutoff_iso, limit=200)

    # build verdict map
    feedbacks = event_log.list_recent(types=["hypothesis_feedback"], limit=500)
    verdict_by_hyp: Dict[str, str] = {}
    for fb in reversed(feedbacks):
        target = fb.payload.get("hypothesis_id")
        v = fb.payload.get("verdict")
        if target and v:
            verdict_by_hyp[target] = v

    beats: list[RhythmBeat] = []
    for h in hyps:
        verdict = verdict_by_hyp.get(h.id, "pending")
        beats.append(
            RhythmBeat(
                timestamp=h.timestamp,
                label=str(h.payload.get("label") or "Steady"),
                verdict=verdict,
            )
        )
    return beats[:20]  # cap at 20 most recent


def _profile_snapshot() -> ProfileSnapshot:
    sections = profile_md.read_sections(sections=["Active Projects"])
    body = sections.get("Active Projects", "")
    # crude project name extraction: bullet lines starting with '- '
    projects: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- "):
            name = line[2:].split("(")[0].strip()
            if name:
                projects.append(name)
    projects = projects[:5]

    last_patch = event_log.latest_one("profile_patch")
    last_at = last_patch.timestamp if last_patch else None
    last_minutes = None
    if last_at:
        ts = _parse_ts(last_at)
        if ts:
            last_minutes = int((_now() - ts).total_seconds() // 60)

    return ProfileSnapshot(
        active_projects_preview=projects,
        last_patch_at=last_at,
        last_patch_minutes_ago=last_minutes,
    )


# --------------------------------------------------------------------------- endpoint


def _latest_hypothesis() -> Optional[LatestHypothesis]:
    rec = event_log.latest_one("hypothesis")
    if rec is None:
        return None
    ts = _parse_ts(rec.timestamp)
    minutes_ago = int((_now() - ts).total_seconds() // 60) if ts else 0

    # Derive status from feedbacks (same logic as hypotheses_view, inlined for one record)
    fbs = event_log.list_recent(types=["hypothesis_feedback"], limit=200)
    status = "active"
    for fb in fbs:
        if fb.payload.get("hypothesis_id") == rec.id:
            v = fb.payload.get("verdict")
            if v in ("confirmed", "rejected", "partial"):
                status = v
                break

    p = rec.payload
    return LatestHypothesis(
        id=rec.id,
        label=str(p.get("label") or "Steady"),
        confidence=float(p.get("confidence") or 0.0),
        summary=str(p.get("summary") or ""),
        source_tag=str(p.get("source_tag") or "checkin"),
        timestamp=rec.timestamp,
        minutes_ago=minutes_ago,
        status=status,
    )


def _latest_checkin() -> Optional[LatestCheckin]:
    rec = event_log.latest_one("checkin")
    if rec is None:
        return None
    ts = _parse_ts(rec.timestamp)
    minutes_ago = int((_now() - ts).total_seconds() // 60) if ts else 0
    p = rec.payload
    return LatestCheckin(
        id=rec.id,
        weather=str(p.get("weather") or ""),
        project=p.get("project"),
        friction_point=p.get("friction_point"),
        free_text=p.get("free_text"),
        timestamp=rec.timestamp,
        minutes_ago=minutes_ago,
    )


@router.get("/snapshot", response_model=DashboardSnapshot)
def snapshot() -> DashboardSnapshot:
    return DashboardSnapshot(
        today_calendar=_today_calendar(),
        this_week_github=_this_week_github(),
        scheduler=_scheduler_heartbeat(),
        pending_proposals_count=_pending_proposals_count(),
        recent_rhythm=_recent_rhythm(),
        profile=_profile_snapshot(),
        latest_hypothesis=_latest_hypothesis(),
        latest_checkin=_latest_checkin(),
    )
