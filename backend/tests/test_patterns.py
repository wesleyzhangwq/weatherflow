"""Pattern detector tests — deterministic, no LLM."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.patterns import detect
from app.memory import git_repo, notes_repo, state_repo
from app.memory.schemas import GitActivityIn, NotesActivityIn, UserStateOut
from app.memory.store import get_conn


def _seed_state(days_ago: int, *, momentum: int, burnout: int, focus: int = 50) -> None:
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    state_repo.add(
        UserStateOut(
            focus=focus,
            stress=50,
            burnout=burnout,
            momentum=momentum,
            confidence=50,
            motivation=50,
            weather_label="Recovery",
            rationale="seed",
        ),
        ts=ts,
    )


def _seed_git(days_ago: int, *, commits: int, switch: float, repo: str = "r") -> None:
    git_repo.add(GitActivityIn(repo=repo, commit_count=commits, switch_score=switch))
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "UPDATE git_activity SET ts=? WHERE id=(SELECT MAX(id) FROM git_activity)",
            (ts,),
        )


def _seed_notes(days_ago: int, *, new_files: int, new_words: int) -> None:
    notes_repo.add(
        NotesActivityIn(
            root="/tmp/notes",
            file_count=10,
            new_file_count=new_files,
            edited_count=new_files,
            total_words=1000,
            new_words=new_words,
            avg_words=100,
        )
    )
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "UPDATE notes_activity SET ts=? WHERE id=(SELECT MAX(id) FROM notes_activity)",
            (ts,),
        )


def test_burnout_climbing_pattern_emitted() -> None:
    # Previous window: low burnout. Current window: high burnout.
    _seed_state(10, momentum=70, burnout=20)
    _seed_state(2, momentum=40, burnout=50)

    report = detect(window_days=7)
    codes = {p.code for p in report.patterns}
    assert "burnout_climbing" in codes


def test_input_up_output_down_pattern_emitted() -> None:
    # Previous window: few new files, decent commits.
    _seed_notes(10, new_files=1, new_words=50)
    _seed_git(10, commits=12, switch=0.2)

    # Current window: many new files (input), no commits (output).
    _seed_notes(2, new_files=15, new_words=80)
    _seed_git(2, commits=2, switch=0.2)

    report = detect(window_days=7)
    codes = {p.code for p in report.patterns}
    assert "input_up_output_down" in codes


def test_quiet_window_emits_no_patterns() -> None:
    report = detect(window_days=7)
    # No data seeded; nothing should fire.
    assert report.patterns == []
    # Metrics should still be present, all zeros.
    assert any(m.name == "commits" for m in report.metrics)


def test_metrics_compute_pct_delta_safely() -> None:
    _seed_git(10, commits=0, switch=0.0)
    _seed_git(2, commits=4, switch=0.1)
    report = detect(window_days=7)
    commits_metric = next(m for m in report.metrics if m.name == "commits")
    # previous=0 -> pct_delta is None (not a divide-by-zero)
    assert commits_metric.previous == 0.0
    assert commits_metric.pct_delta is None
