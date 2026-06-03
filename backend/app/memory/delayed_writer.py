"""DelayedMemoryWriter — the gate from L1 fact to L3 profile (§9.2).

Four rules, all must pass:
  A. Event-type whitelist (confirmed hypothesis, executed_action, preferences)
  B. Per-section cooldown (24 hours)
  C. Repetition threshold (Rhythm Patterns / Anti-patterns only — 3 in 14d)
  D. LLM-asserted confidence >= 0.6

ADR D7: the LLM returns `{"diff": "...", "confidence": 0.X}`. We replace the
section content with `diff`, log the change as a `profile_patch` event, and
record the timestamp for future cooldown checks.

Triggers:
  - T1 / T3 / T4 completion → `asyncio.create_task(maybe_update())`
  - Every 12 hours (scheduler heartbeat) as a safety net
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.core.llm import LLMClient, build_llm_client, chat_json
from app.memory import event_log, profile_md
from app.memory.schemas import (
    EventRecord,
    ProfilePatchPayload,
    ProfileSection,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- candidate model


@dataclass
class Candidate:
    target_section: ProfileSection
    seed_events: List[EventRecord]


def _classify(event: EventRecord, paired_label: Optional[str]) -> Optional[ProfileSection]:
    """Map an L1 event to a target profile section.

    `paired_label` is set when the event is a confirmed hypothesis and we
    want to bucket by its label (Rhythm vs Anti-pattern depends on the label).
    """
    if event.type == "hypothesis" and paired_label:
        if paired_label in ("Overload", "Blocked", "Fragmented"):
            return "Anti-patterns"
        return "Rhythm Patterns"
    if event.type == "executed_action":
        return "Active Projects"
    return None


# --------------------------------------------------------------------------- main entry


async def maybe_update(
    *, llm: Optional[LLMClient] = None, user_id: Optional[str] = None
) -> Dict[str, Any]:
    s = get_settings()
    uid = user_id or s.default_user_id

    candidates = _collect_candidates(uid)
    if not candidates:
        return {"status": "nothing_to_do", "candidates": 0}

    owns_llm = False
    if llm is None:
        llm = build_llm_client()
        owns_llm = True
    try:
        patches: list[dict[str, Any]] = []
        for cand in candidates:
            section = cand.target_section
            if _within_cooldown(section, uid, hours=s.dmw_section_cooldown_hours):
                continue
            if not _meets_repetition_threshold(cand, settings=s):
                continue
            current_text = profile_md.read_sections(sections=[section], user_id=uid)[section]
            patch = await _llm_patch(
                llm=llm,
                section=section,
                current_text=current_text,
                seed_events=cand.seed_events,
            )
            if patch is None:
                continue
            if patch["confidence"] < s.dmw_min_confidence:
                logger.info(
                    "DMW skipping %s (confidence %.2f < %.2f)",
                    section, patch["confidence"], s.dmw_min_confidence,
                )
                continue
            profile_md.apply_patch(section, patch["diff"], user_id=uid)
            event_log.append(
                type="profile_patch",
                payload=ProfilePatchPayload(
                    section=section,
                    diff=patch["diff"],
                    confidence=patch["confidence"],
                    note=patch.get("note"),
                ).model_dump(),
                refs={"triggered_by": [e.id for e in cand.seed_events]},
            )
            patches.append({"section": section, "confidence": patch["confidence"]})

        return {"status": "ok", "patches_applied": patches, "candidates": len(candidates)}
    finally:
        if owns_llm:
            await llm.aclose()


# --------------------------------------------------------------------------- candidate collection


def _collect_candidates(user_id: str) -> List[Candidate]:
    """Rule A — gather high-signal events since last DMW run."""
    feedback_events = event_log.list_recent(
        user_id=user_id, types=["hypothesis_feedback"], limit=200
    )
    confirmed_hyp_ids = {
        fb.payload["hypothesis_id"]
        for fb in feedback_events
        if fb.payload.get("verdict") == "confirmed"
    }
    confirmed_hyps: list[tuple[EventRecord, str]] = []
    if confirmed_hyp_ids:
        hyps = event_log.list_recent(
            user_id=user_id, types=["hypothesis"], limit=300
        )
        for h in hyps:
            if h.id in confirmed_hyp_ids:
                confirmed_hyps.append((h, h.payload.get("label", "")))

    executed = event_log.list_recent(
        user_id=user_id, types=["executed_action"], limit=100
    )

    buckets: Dict[ProfileSection, List[EventRecord]] = {}
    for h, label in confirmed_hyps:
        target = _classify(h, paired_label=label)
        if target:
            buckets.setdefault(target, []).append(h)
    for e in executed:
        target = _classify(e, paired_label=None)
        if target:
            buckets.setdefault(target, []).append(e)

    return [Candidate(target_section=k, seed_events=v) for k, v in buckets.items()]


# --------------------------------------------------------------------------- thresholds


def _within_cooldown(section: ProfileSection, user_id: str, *, hours: int) -> bool:
    patches = event_log.list_recent(user_id=user_id, types=["profile_patch"], limit=50)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for p in patches:
        if p.payload.get("section") != section:
            continue
        try:
            ts = datetime.fromisoformat(p.timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts > cutoff:
            logger.info(
                "DMW cooldown active for %s (last patch %s)", section, p.timestamp
            )
            return True
    return False


def _meets_repetition_threshold(cand: Candidate, *, settings) -> bool:
    if cand.target_section not in ("Rhythm Patterns", "Anti-patterns"):
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.dmw_pattern_window_days)
    counts: Counter[str] = Counter()
    for ev in cand.seed_events:
        try:
            ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts <= cutoff:
            continue
        label = ev.payload.get("label")
        if label:
            counts[label] += 1
    if not counts:
        return False
    top = counts.most_common(1)[0][1]
    if top < settings.dmw_pattern_min_count:
        logger.info(
            "DMW repetition threshold not met for %s (top count %d < %d)",
            cand.target_section, top, settings.dmw_pattern_min_count,
        )
        return False
    return True


# --------------------------------------------------------------------------- LLM patch


_SYSTEM_PROMPT_PATCH = """你是 WeatherFlow 的 Profile 维护器。给定 (a) profile.md 某章节的当前内容，(b) 一组 ground-truth 事件（用户已校准为 confirmed 的 hypothesis 或已执行的 action），请输出该章节的新内容。

要求：
1. 输出严格 JSON：{"diff": "<新的整章节内容（markdown 片段）>", "confidence": <0.0~1.0>, "note": "<可选简短说明>"}。
2. 不要包含章节标题（# Section）；只输出章节正文。
3. 保留用户手写的有价值条目；只新增/修订模式相关条目。
4. confidence 反映你对"这条规律真的稳定"的信心。低于 0.6 视为放弃。
5. 不要写废话；如果证据不足以让你 confidence > 0.6，老实输出低 confidence。
"""


async def _llm_patch(
    *,
    llm: LLMClient,
    section: ProfileSection,
    current_text: str,
    seed_events: List[EventRecord],
) -> Optional[Dict[str, Any]]:
    seed_summary = "\n".join(
        f"- ({e.type} {e.timestamp}) "
        + json.dumps(e.payload, ensure_ascii=False)[:200]
        for e in seed_events[:10]
    )
    user_msg = (
        f"Section: {section}\n\n"
        f"Current content:\n---\n{current_text}\n---\n\n"
        f"Ground-truth seed events:\n{seed_summary}\n"
    )
    try:
        data = await chat_json(
            llm,
            [
                {"role": "system", "content": _SYSTEM_PROMPT_PATCH},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )
    except Exception:
        logger.exception("DMW LLM call failed")
        return None
    if not isinstance(data, dict):
        return None
    diff = data.get("diff")
    confidence = data.get("confidence")
    if not isinstance(diff, str) or not isinstance(confidence, (int, float)):
        return None
    return {
        "diff": diff.strip(),
        "confidence": float(confidence),
        "note": data.get("note"),
    }


__all__ = ["maybe_update"]
