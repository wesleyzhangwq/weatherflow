"""CRUD helpers for dev review agent runs and reports."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.memory.schemas import (
    AgentRunCreate,
    AgentRunRecord,
    AgentRunStep,
    DevReviewCreate,
    DevReviewRecord,
    RunStatus,
)
from app.memory.store import get_conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _run_from_row(row: Any) -> AgentRunRecord:
    data = dict(row)
    return AgentRunRecord(
        id=data["id"],
        run_type=data["run_type"],
        status=data["status"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        input=_json_loads(data["input_json"], {}),
        steps=[AgentRunStep(**step) for step in _json_loads(data["steps_json"], [])],
        error=data["error"],
    )


def _review_from_row(row: Any, run: AgentRunRecord) -> DevReviewRecord:
    data = dict(row)
    return DevReviewRecord(
        id=data["id"],
        run_id=data["run_id"],
        window_days=data["window_days"],
        summary=data["summary"],
        dev_weather=data["dev_weather"],
        main_work_threads=_json_loads(data["main_work_threads_json"], []),
        shipping_progress=_json_loads(data["shipping_progress_json"], []),
        collaboration_load=_json_loads(data["collaboration_load_json"], []),
        meeting_load=_json_loads(data["meeting_load_json"], []),
        rhythm_risks=_json_loads(data["rhythm_risks_json"], []),
        next_week_suggestion=data["next_week_suggestion"],
        source_coverage=_json_loads(data["source_coverage_json"], {}),
        created_at=data["created_at"],
        run=run,
    )


def create_run(payload: AgentRunCreate) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_runs (run_type, input_json)
            VALUES (?, ?)
            """,
            (payload.run_type, _json_dumps(payload.input)),
        )
        return int(cur.lastrowid)


def get_run(run_id: int) -> Optional[AgentRunRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, run_type, status, started_at, finished_at, input_json, steps_json, error
            FROM agent_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    if not row:
        return None
    return _run_from_row(row)


def append_step(run_id: int, step: AgentRunStep) -> AgentRunRecord:
    current = get_run(run_id)
    if current is None:
        raise ValueError(f"agent run {run_id} not found")

    steps = [item.model_dump() for item in current.steps]
    steps.append(step.model_dump())
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_runs SET steps_json = ? WHERE id = ?",
            (_json_dumps(steps), run_id),
        )
    updated = get_run(run_id)
    if updated is None:
        raise ValueError(f"agent run {run_id} not found")
    return updated


def finish_run(run_id: int, *, status: RunStatus, error: str | None = None) -> AgentRunRecord:
    if get_run(run_id) is None:
        raise ValueError(f"agent run {run_id} not found")

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, finished_at = datetime('now'), error = ?
            WHERE id = ?
            """,
            (status, error, run_id),
        )
    updated = get_run(run_id)
    if updated is None:
        raise ValueError(f"agent run {run_id} not found")
    return updated


def create_review(payload: DevReviewCreate) -> int:
    if get_run(payload.run_id) is None:
        raise ValueError(f"agent run {payload.run_id} not found")

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO dev_reviews (
                run_id,
                window_days,
                summary,
                dev_weather,
                main_work_threads_json,
                shipping_progress_json,
                collaboration_load_json,
                meeting_load_json,
                rhythm_risks_json,
                next_week_suggestion,
                source_coverage_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.run_id,
                payload.window_days,
                payload.summary,
                payload.dev_weather,
                _json_dumps(payload.main_work_threads),
                _json_dumps(payload.shipping_progress),
                _json_dumps(payload.collaboration_load),
                _json_dumps(payload.meeting_load),
                _json_dumps(payload.rhythm_risks),
                payload.next_week_suggestion,
                _json_dumps(payload.source_coverage),
            ),
        )
        return int(cur.lastrowid)


def get_review(review_id: int) -> Optional[DevReviewRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                run_id,
                window_days,
                summary,
                dev_weather,
                main_work_threads_json,
                shipping_progress_json,
                collaboration_load_json,
                meeting_load_json,
                rhythm_risks_json,
                next_week_suggestion,
                source_coverage_json,
                created_at
            FROM dev_reviews
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()
    if not row:
        return None

    run = get_run(int(row["run_id"]))
    if run is None:
        raise ValueError(f"agent run {row['run_id']} not found")
    return _review_from_row(row, run)


def latest_review() -> Optional[DevReviewRecord]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                run_id,
                window_days,
                summary,
                dev_weather,
                main_work_threads_json,
                shipping_progress_json,
                collaboration_load_json,
                meeting_load_json,
                rhythm_risks_json,
                next_week_suggestion,
                source_coverage_json,
                created_at
            FROM dev_reviews
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return None

    run = get_run(int(row["run_id"]))
    if run is None:
        raise ValueError(f"agent run {row['run_id']} not found")
    return _review_from_row(row, run)


def latest_review_for_run(run_id: int) -> Optional[DevReviewRecord]:
    if get_run(run_id) is None:
        raise ValueError(f"agent run {run_id} not found")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                run_id,
                window_days,
                summary,
                dev_weather,
                main_work_threads_json,
                shipping_progress_json,
                collaboration_load_json,
                meeting_load_json,
                rhythm_risks_json,
                next_week_suggestion,
                source_coverage_json,
                created_at
            FROM dev_reviews
            WHERE run_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    if not row:
        return None

    run = get_run(run_id)
    if run is None:
        raise ValueError(f"agent run {run_id} not found")
    return _review_from_row(row, run)


__all__ = [
    "create_run",
    "get_run",
    "append_step",
    "finish_run",
    "create_review",
    "get_review",
    "latest_review",
    "latest_review_for_run",
]
