from __future__ import annotations

from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate, AgentRunStep, DevReviewCreate
from app.memory.store import get_conn


def test_dev_review_schema_uses_json_column_names_and_defaults() -> None:
    with get_conn() as conn:
        rows = conn.execute("PRAGMA table_info(dev_reviews)").fetchall()

    columns = {row["name"]: dict(row) for row in rows}

    expected_json_defaults = {
        "main_work_threads_json": "'[]'",
        "shipping_progress_json": "'[]'",
        "collaboration_load_json": "'[]'",
        "meeting_load_json": "'[]'",
        "rhythm_risks_json": "'[]'",
        "source_coverage_json": "'{}'",
    }
    for column_name, default in expected_json_defaults.items():
        assert columns[column_name]["type"] == "TEXT"
        assert columns[column_name]["notnull"] == 1
        assert columns[column_name]["dflt_value"] == default

    assert columns["window_days"]["type"] == "INTEGER"
    assert columns["window_days"]["notnull"] == 1
    assert columns["window_days"]["dflt_value"] == "7"


def test_dev_review_roundtrip_with_attached_partial_run() -> None:
    run_id = dev_review_repo.create_run(
        AgentRunCreate(
            input={
                "window_days": 7,
                "providers": ["github", "google_calendar"],
            }
        )
    )

    dev_review_repo.append_step(
        run_id,
        AgentRunStep(
            name="github",
            status="success",
            summary="Found steady collaboration-heavy work.",
            metadata={"commits": 4, "prs": 2},
        ),
    )
    dev_review_repo.finish_run(run_id, status="partial")

    review_id = dev_review_repo.create_review(
        DevReviewCreate(
            run_id=run_id,
            window_days=7,
            summary="A useful week with collaboration carrying most of the load.",
            dev_weather="Collaboration Heavy",
            main_work_threads=["dev review agent", "memory persistence"],
            shipping_progress=["persisted review data"],
            collaboration_load=["PR review", "calendar-heavy coordination"],
            meeting_load=["planning", "syncs"],
            rhythm_risks=["fragmented maker time"],
            next_week_suggestion="Protect one deep-work block before meetings.",
            source_coverage={
                "github": {"status": "success"},
            },
        )
    )

    latest = dev_review_repo.latest_review()

    assert latest is not None
    assert latest.id == review_id
    assert latest.run.id == run_id
    assert latest.run.status == "partial"
    assert latest.run.steps[0].name == "github"
    assert latest.dev_weather == "Collaboration Heavy"
    assert "google_calendar" not in latest.source_coverage
