from __future__ import annotations

from weatherflow_cli.dev_review import _history_lines


def test_history_lines_summarize_recent_reviews() -> None:
    lines = _history_lines(
        [
            {
                "created_at": "2026-05-19T10:00:00",
                "dev_weather": "Shipping",
                "run": {"status": "partial"},
                "source_coverage": {
                    "github": {"status": "success"},
                    "google_calendar": {"status": "skipped"},
                },
            }
        ]
    )

    assert lines == [
        "Dev Review History",
        "- 2026-05-19T10:00:00 · Shipping · partial · github: success · google_calendar: skipped",
    ]


def test_history_lines_handles_empty_history() -> None:
    assert _history_lines([]) == ["No dev reviews have been saved yet."]
