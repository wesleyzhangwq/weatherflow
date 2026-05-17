from __future__ import annotations

import sqlite3

from app.memory import dev_review_repo
from app.memory.schemas import AgentRunCreate, AgentRunStep, DevReviewCreate
from app.memory.store import get_conn, init_db, set_db_path


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


def test_init_db_migrates_legacy_dev_review_json_columns(tmp_path) -> None:
    db_path = str(tmp_path / "legacy-dev-review.db")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE agent_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type     TEXT    NOT NULL CHECK (run_type IN ('dev_review')),
                status       TEXT    NOT NULL DEFAULT 'running'
                                     CHECK (status IN ('running','success','partial','failed')),
                started_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                finished_at  TEXT,
                input_json   TEXT    NOT NULL DEFAULT '{}',
                steps_json   TEXT    NOT NULL DEFAULT '[]',
                error        TEXT
            );
            CREATE TABLE dev_reviews (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id                INTEGER NOT NULL REFERENCES agent_runs(id),
                window_days           INTEGER NOT NULL,
                summary               TEXT    NOT NULL,
                dev_weather           TEXT    NOT NULL
                                      CHECK (dev_weather IN ('Deep Work','Shipping','Collaboration Heavy','Fragmented','Blocked')),
                main_work_threads     TEXT    NOT NULL,
                shipping_progress     TEXT    NOT NULL,
                collaboration_load    TEXT    NOT NULL,
                meeting_load          TEXT    NOT NULL,
                rhythm_risks          TEXT    NOT NULL,
                next_week_suggestion  TEXT    NOT NULL,
                source_coverage       TEXT    NOT NULL,
                created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO agent_runs (run_type, status, input_json, steps_json)
            VALUES ('dev_review', 'success', '{"window_days": 7}', '[]');
            INSERT INTO dev_reviews (
                run_id,
                window_days,
                summary,
                dev_weather,
                main_work_threads,
                shipping_progress,
                collaboration_load,
                meeting_load,
                rhythm_risks,
                next_week_suggestion,
                source_coverage
            )
            VALUES (
                1,
                7,
                'Legacy review',
                'Shipping',
                '["legacy thread"]',
                '["legacy shipped"]',
                '["legacy collaboration"]',
                '["legacy meeting"]',
                '["legacy risk"]',
                'Keep shipping.',
                '{"github": {"status": "success"}}'
            );
            """
        )

    set_db_path(db_path)
    init_db(db_path)

    old_review = dev_review_repo.get_review(1)
    assert old_review is not None
    assert old_review.main_work_threads == ["legacy thread"]
    assert old_review.source_coverage["github"]["status"] == "success"

    new_run_id = dev_review_repo.create_run(AgentRunCreate(input={"window_days": 7}))
    new_review_id = dev_review_repo.create_review(
        DevReviewCreate(
            run_id=new_run_id,
            summary="Current review",
            dev_weather="Deep Work",
            main_work_threads=["current thread"],
            shipping_progress=[],
            collaboration_load=[],
            meeting_load=[],
            rhythm_risks=[],
            next_week_suggestion="Stay focused.",
            source_coverage={},
        )
    )

    new_review = dev_review_repo.get_review(new_review_id)
    assert new_review is not None
    assert new_review.main_work_threads == ["current thread"]
