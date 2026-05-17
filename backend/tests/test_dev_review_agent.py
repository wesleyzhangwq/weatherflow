from __future__ import annotations

from typing import Any

import pytest

from app.agents.dev_review_agent import DevReviewAgent
from app.memory.schemas import DevWeather, ProviderContext


class FailingLLM:
    async def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("LLM unavailable")


def _contexts(
    *,
    events: int,
    meeting_hours: float,
    repos: list[str] | None = None,
) -> list[ProviderContext]:
    repos = repos or ["owner/weatherflow"]
    return [
        ProviderContext(
            source="github",
            status="success",
            window_days=7,
            signals={
                "events": events,
                "repos": repos,
                "event_types": {"PullRequestEvent": min(events, 2)} if events else {},
            },
        ),
        ProviderContext(
            source="google_calendar",
            status="success",
            window_days=7,
            signals={
                "meeting_count": 1 if meeting_hours else 0,
                "meeting_hours": meeting_hours,
                "events": [{"title": "WeatherFlow architecture sync"}] if meeting_hours else [],
            },
        ),
    ]


async def test_dev_review_agent_fallback_uses_provider_signals() -> None:
    agent = DevReviewAgent(FailingLLM())
    contexts = [
        ProviderContext(
            source="github",
            status="success",
            window_days=7,
            signals={
                "events": 8,
                "repos": ["owner/weatherflow"],
                "event_types": {"PullRequestEvent": 2},
            },
        ),
        ProviderContext(
            source="google_calendar",
            status="success",
            window_days=7,
            signals={
                "meeting_count": 12,
                "meeting_hours": 8.5,
                "events": [{"title": "WeatherFlow architecture sync"}],
            },
        ),
    ]

    review = await agent.synthesize(window_days=7, contexts=contexts)

    assert review.dev_weather in DevWeather.__args__
    assert review.summary
    assert "owner/weatherflow" in review.main_work_threads[0]
    assert "12" in " ".join(review.meeting_load)
    assert review.source_coverage["github"]["status"] == "success"
    assert review.source_coverage["google_calendar"]["status"] == "success"


@pytest.mark.parametrize(
    ("events", "meeting_hours", "repos", "expected"),
    [
        (0, 8.0, ["owner/weatherflow"], "Blocked"),
        (1, 10.0, ["owner/weatherflow"], "Collaboration Heavy"),
        (
            4,
            9.5,
            ["owner/api", "owner/web", "owner/docs", "owner/infra"],
            "Fragmented",
        ),
        (8, 7.5, ["owner/weatherflow"], "Shipping"),
        (3, 2.0, ["owner/weatherflow"], "Deep Work"),
    ],
)
async def test_dev_review_agent_fallback_weather_heuristic_precedence(
    events: int,
    meeting_hours: float,
    repos: list[str],
    expected: DevWeather,
) -> None:
    agent = DevReviewAgent(FailingLLM())

    review = await agent.synthesize(
        window_days=7,
        contexts=_contexts(events=events, meeting_hours=meeting_hours, repos=repos),
    )

    assert review.dev_weather == expected
