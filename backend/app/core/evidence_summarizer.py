"""LLM-driven evidence summarizer used by T2 (§8.3).

Takes the freshly-pulled calendar + github snapshots and produces a short
natural-language `evidence_summary`. The summary is what later hypothesis
generations will see in Bundle (instead of the raw snapshots), keeping the
prompt token budget under control. Raw snapshots remain in L1 for drill-down.
"""

from __future__ import annotations

import json
import logging

from app.core.llm import LLMClient, chat_json
from app.memory.schemas import (
    CalendarSnapshotPayload,
    EvidenceSummaryPayload,
    GithubSnapshotPayload,
)

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """你是 WeatherFlow 的 evidence 摘要器。给定过去几天的 Calendar 与 GitHub 数据，请输出一段简短的、面向后续节奏判断的中文摘要 (<= 200 字)，并附带几个关键数字指标。

输出严格 JSON：
{
  "text": "...摘要文本（中文，1-3 句）...",
  "headline_metrics": {
    "meeting_count": <int>,
    "meeting_minutes": <int>,
    "commit_count": <int>,
    "open_prs": <int>,
    "active_repos": <int>
  }
}
"""


async def summarize(
    *,
    llm: LLMClient,
    calendar: CalendarSnapshotPayload,
    github: GithubSnapshotPayload,
) -> EvidenceSummaryPayload:
    user_msg = {
        "calendar": calendar.model_dump(),
        "github": github.model_dump(),
    }
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_msg, ensure_ascii=False)[:6000]},
    ]
    try:
        # chat_json strips reasoning-model <think> blocks and tolerantly extracts JSON.
        # Reasoning models like MiniMax-M2.7 / DeepSeek-R1 burn many tokens on
        # think blocks — give the call plenty of headroom so the actual JSON
        # at the end isn't truncated.
        data = await chat_json(
            llm,
            messages,
            temperature=0.2,
            max_tokens=4000,
        )
        text = str(data.get("text", "")).strip()
        metrics = data.get("headline_metrics", {}) or {}
        if not text:
            raise ValueError("empty summary text")
        return EvidenceSummaryPayload(text=text, headline_metrics=metrics)
    except Exception as exc:
        logger.warning("evidence_summary LLM call failed: %s", exc)
        # Fallback: deterministic summary so the system stays functional.
        return _fallback(calendar, github)


def _fallback(
    calendar: CalendarSnapshotPayload, github: GithubSnapshotPayload
) -> EvidenceSummaryPayload:
    meeting_min = sum(int(e.get("duration_minutes") or 0) for e in calendar.events)
    metrics = {
        "meeting_count": len(calendar.events),
        "meeting_minutes": meeting_min,
        "commit_count": len(github.commits),
        "open_prs": len(github.prs),
        "active_repos": len(github.active_repos),
    }
    text = (
        f"过去 {github.window_days} 天: {metrics['commit_count']} commits, "
        f"{metrics['open_prs']} 个 open PR, 活跃 repo {metrics['active_repos']} 个; "
        f"Calendar 窗口: {metrics['meeting_count']} 场会议 (~{meeting_min} 分钟)。"
    )
    return EvidenceSummaryPayload(text=text, headline_metrics=metrics)


__all__ = ["summarize"]
