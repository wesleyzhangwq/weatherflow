"""Dev Review Agent — synthesize provider signals into a weekly dev review."""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.core.llm import chat_json
from app.core.prompts import DEV_REVIEW_SYSTEM
from app.memory.schemas import DevReviewCreate, DevWeather, ProviderContext

_VALID_DEV_WEATHER = set(DevWeather.__args__)


class DevReviewAgent(BaseAgent):
    async def synthesize(
        self,
        window_days: int,
        contexts: list[ProviderContext],
    ) -> DevReviewCreate:
        source_coverage = _source_coverage(contexts)
        payload = {
            "window_days": window_days,
            "provider_contexts": [context.model_dump() for context in contexts],
            "source_coverage": source_coverage,
            "required_run_id": 0,
        }
        messages = [
            {"role": "system", "content": DEV_REVIEW_SYSTEM},
            {
                "role": "user",
                "content": (
                    "请根据以下结构化 provider evidence 输出严格 JSON。"
                    "run_id 先固定为 0，source_coverage 必须保留输入中的 provider 状态。\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2)
                ),
            },
        ]

        try:
            raw = await self._chat_json(messages, temperature=0.3, max_tokens=900)
            if not isinstance(raw, dict):
                raise TypeError("Dev review LLM response must be a JSON object")
            return DevReviewCreate(
                run_id=0,
                window_days=window_days,
                source_coverage=source_coverage,
                **{
                    key: value
                    for key, value in raw.items()
                    if key not in {"run_id", "window_days", "source_coverage"}
                },
            )
        except Exception:
            return _fallback_review(
                window_days=window_days,
                contexts=contexts,
                source_coverage=source_coverage,
            )

    async def _chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        llm_chat_json = getattr(self.llm, "chat_json", None)
        if callable(llm_chat_json):
            return await llm_chat_json(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return await chat_json(
            self.llm,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _source_coverage(contexts: list[ProviderContext]) -> dict[str, Any]:
    return {
        context.source: {
            "status": context.status,
            "window_days": context.window_days,
            "coverage": context.coverage,
            "warnings": context.warnings,
        }
        for context in contexts
    }


def _fallback_review(
    *,
    window_days: int,
    contexts: list[ProviderContext],
    source_coverage: dict[str, Any],
) -> DevReviewCreate:
    github = _signals_for(contexts, "github")
    calendar = _signals_for(contexts, "google_calendar")

    events = _as_int(github.get("events"))
    repos = [str(repo) for repo in github.get("repos") or [] if str(repo)]
    repos_count = _as_int(github.get("repos_touched"), default=len(repos))
    event_types = {
        str(name): _as_int(count)
        for name, count in dict(github.get("event_types") or {}).items()
    }
    meeting_count = _as_int(calendar.get("meeting_count"))
    meeting_hours = _as_float(calendar.get("meeting_hours"))
    event_titles = _calendar_titles(calendar.get("events"))[:3]
    dev_weather = _fallback_weather(
        events=events,
        meeting_hours=meeting_hours,
        repos_count=repos_count,
    )

    main_work_threads = _main_work_threads(repos, events, repos_count)
    shipping_progress = _shipping_progress(events, event_types)
    collaboration_load = _collaboration_load(event_types, meeting_count, meeting_hours)
    meeting_load = _meeting_load(meeting_count, meeting_hours, event_titles)
    rhythm_risks = _rhythm_risks(
        events=events,
        repos_count=repos_count,
        meeting_hours=meeting_hours,
        meeting_count=meeting_count,
    )

    summary = (
        f"过去 {window_days} 天，工具信号显示 GitHub 有 {events} 个事件，"
        f"涉及 {repos_count} 个仓库；日历记录 {meeting_count} 场会议，约 {meeting_hours:g} 小时。"
        f"本次判断为「{dev_weather}」，仅基于这些 provider evidence。"
    )

    return DevReviewCreate(
        run_id=0,
        window_days=window_days,
        summary=summary,
        dev_weather=dev_weather,
        main_work_threads=main_work_threads,
        shipping_progress=shipping_progress,
        collaboration_load=collaboration_load,
        meeting_load=meeting_load,
        rhythm_risks=rhythm_risks,
        next_week_suggestion=_next_week_suggestion(dev_weather),
        source_coverage=source_coverage,
    )


def _signals_for(contexts: list[ProviderContext], source: str) -> dict[str, Any]:
    for context in contexts:
        if context.source == source:
            return dict(context.signals)
    return {}


def _fallback_weather(*, events: int, meeting_hours: float, repos_count: int) -> str:
    if events == 0 and meeting_hours >= 8:
        return "Blocked"
    if meeting_hours >= 10:
        return "Collaboration Heavy"
    if repos_count >= 4:
        return "Fragmented"
    if events >= 8:
        return "Shipping"
    return "Deep Work"


def _main_work_threads(repos: list[str], events: int, repos_count: int) -> list[str]:
    if repos:
        return [
            f"仓库 {repo} 是主要工作线索（GitHub 事件 {events} 个）。"
            for repo in repos[:3]
        ]
    if repos_count:
        return [f"GitHub 信号覆盖了 {repos_count} 个仓库。"]
    return ["GitHub 未提供明确仓库线索。"]


def _shipping_progress(events: int, event_types: dict[str, int]) -> list[str]:
    items = []
    pull_requests = event_types.get("PullRequestEvent", 0)
    push_events = event_types.get("PushEvent", 0)
    if events:
        items.append(f"GitHub 在窗口内记录了 {events} 个开发事件。")
    if pull_requests:
        items.append(f"PullRequestEvent 有 {pull_requests} 次，显示有 PR 相关推进。")
    if push_events:
        items.append(f"PushEvent 有 {push_events} 次，显示有代码提交活动。")
    return items


def _collaboration_load(
    event_types: dict[str, int],
    meeting_count: int,
    meeting_hours: float,
) -> list[str]:
    items = []
    pull_requests = event_types.get("PullRequestEvent", 0)
    issue_comments = event_types.get("IssueCommentEvent", 0)
    if pull_requests:
        items.append(f"PR 相关事件 {pull_requests} 次。")
    if issue_comments:
        items.append(f"Issue 评论事件 {issue_comments} 次。")
    if meeting_count:
        items.append(f"日历会议 {meeting_count} 场，约 {meeting_hours:g} 小时。")
    return items


def _meeting_load(
    meeting_count: int,
    meeting_hours: float,
    event_titles: list[str],
) -> list[str]:
    items = [f"日历共有 {meeting_count} 场会议，约 {meeting_hours:g} 小时。"]
    if event_titles:
        items.append("会议标题示例：" + "、".join(event_titles))
    return items


def _rhythm_risks(
    *,
    events: int,
    repos_count: int,
    meeting_hours: float,
    meeting_count: int,
) -> list[str]:
    risks = []
    if events == 0 and meeting_hours >= 8:
        risks.append("日历会议时长较高，同时 GitHub 没有事件记录，可能缺少可见产出信号。")
    if meeting_hours >= 10:
        risks.append(f"会议时长约 {meeting_hours:g} 小时，可能压缩连续开发时间。")
    if repos_count >= 4:
        risks.append(f"GitHub 信号分布在 {repos_count} 个仓库，工作线索可能较分散。")
    if meeting_count >= 12:
        risks.append(f"会议数量达到 {meeting_count} 场，需要留意日程碎片化。")
    return risks


def _next_week_suggestion(dev_weather: str) -> str:
    suggestions = {
        "Blocked": "下周可以先确认一个能留下可见代码或 PR 信号的小闭环。",
        "Collaboration Heavy": "下周可以预留一段不被会议切开的开发时间。",
        "Fragmented": "下周可以把主要仓库先收束到一到两个最重要的线索上。",
        "Shipping": "下周可以延续当前推进节奏，同时给收尾和复盘留一点空间。",
        "Deep Work": "下周可以继续保留当前的连续工作节奏。",
    }
    return suggestions.get(dev_weather, suggestions["Deep Work"])


def _calendar_titles(events: Any) -> list[str]:
    if not isinstance(events, list):
        return []
    titles = []
    for event in events:
        if isinstance(event, dict):
            title = str(event.get("title") or "").strip()
            if title:
                titles.append(title)
    return titles


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["DevReviewAgent"]
