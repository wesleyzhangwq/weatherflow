from __future__ import annotations

from typing import Any

from app.agents.dev_review_agent import DevReviewAgent
from app.memory.schemas import DevWeather, ProviderContext


class FailingLLM:
    async def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("LLM unavailable")


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
