from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.mcp.github import normalize_github_summary
from app.mcp.google_calendar import GoogleCalendarConnector, sanitize_calendar_events


def test_normalize_github_summary_maps_connector_payload_to_provider_context() -> None:
    context = normalize_github_summary(
        {
            "login": "octocat",
            "events": 3,
            "by_type": {"PushEvent": 2, "PullRequestEvent": 1},
            "repos_touched": 2,
            "repo_list": ["weather/app", "weather/docs"],
        },
        window_days=14,
    )

    assert context.source == "github"
    assert context.status == "success"
    assert context.window_days == 14
    assert context.signals == {
        "login": "octocat",
        "events": 3,
        "event_types": {"PushEvent": 2, "PullRequestEvent": 1},
        "repos_touched": 2,
        "repos": ["weather/app", "weather/docs"],
    }
    assert context.coverage == {
        "login": "octocat",
        "raw_event_count": 3,
    }
    assert context.warnings == []


def test_normalize_github_summary_warns_when_window_has_no_events() -> None:
    context = normalize_github_summary(
        {
            "login": "octocat",
            "events": 0,
            "by_type": {},
            "repos_touched": 0,
            "repo_list": [],
        },
        window_days=7,
    )

    assert context.signals["events"] == 0
    assert context.warnings == ["No recent GitHub events returned for this window."]


def test_sanitize_calendar_events_keeps_safe_event_title_time_duration_and_category() -> None:
    events = sanitize_calendar_events(
        [
            {
                "summary": "Review API design",
                "description": "private notes",
                "attendees": [{"email": "teammate@example.com"}],
                "hangoutLink": "https://meet.google.com/private-room",
                "conferenceData": {"entryPoints": [{"uri": "https://zoom.example/private"}]},
                "location": "Home office",
                "attachments": [{"title": "confidential.pdf"}],
                "start": {"dateTime": "2026-05-17T09:00:00-07:00"},
                "end": {"dateTime": "2026-05-17T09:45:00-07:00"},
                "organizer": {"displayName": "Work Calendar"},
            }
        ]
    )

    assert events == [
        {
            "title": "Review API design",
            "start": "2026-05-17T09:00:00-07:00",
            "duration_minutes": 45,
            "calendar_name": "Work Calendar",
            "category": "review",
        }
    ]
    assert "description" not in events[0]
    assert "attendees" not in events[0]
    assert "hangoutLink" not in events[0]
    assert "location" not in events[0]
    assert "attachments" not in events[0]


def test_sanitize_calendar_events_returns_zero_duration_for_all_day_events() -> None:
    events = sanitize_calendar_events(
        [
            {
                "summary": "Team offsite",
                "start": {"date": "2026-05-17"},
                "end": {"date": "2026-05-18"},
            }
        ]
    )

    assert events == [
        {
            "title": "Team offsite",
            "start": "2026-05-17",
            "duration_minutes": 0,
            "calendar_name": "",
            "category": "meeting",
        }
    ]


async def test_google_calendar_fetch_normalizes_events_without_counting_all_day_as_after_hours(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "items": [
                    {
                        "summary": "Product sync",
                        "start": {"dateTime": "2026-05-17T10:00:00-07:00"},
                        "end": {"dateTime": "2026-05-17T11:00:00-07:00"},
                    },
                    {
                        "summary": "Focus day",
                        "start": {"date": "2026-05-18"},
                        "end": {"date": "2026-05-19"},
                    },
                ]
            }

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
            captured["path"] = args[0]
            captured["params"] = kwargs["params"]
            captured["called_at"] = datetime.now(timezone.utc)
            return FakeResponse()

    connector = GoogleCalendarConnector("token", calendar_id="primary")
    monkeypatch.setattr(connector, "_client", lambda: FakeClient())

    context = await connector.fetch(days=7)

    assert context.source == "google_calendar"
    assert context.status == "success"
    assert context.signals["meeting_count"] == 2
    assert context.signals["meeting_hours"] == 1.0
    assert context.signals["after_hours_events"] == 0
    assert context.coverage == {"calendar_id": "primary", "event_count": 2}

    assert captured["path"] == "/calendars/primary/events"
    assert captured["params"]["singleEvents"] == "true"
    assert captured["params"]["orderBy"] == "startTime"
    assert captured["params"]["maxResults"] == 100
    time_min = datetime.fromisoformat(captured["params"]["timeMin"])
    time_max = datetime.fromisoformat(captured["params"]["timeMax"])
    assert time_min < time_max
    assert time_max <= captured["called_at"]
