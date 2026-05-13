"""Bundled sensor sweep."""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.sensors.sweep_runner import run_sensor_sweep


def test_sensor_sweep_dry_run_minimal(tmp_path: Path) -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    empty = tmp_path / "empty"
    empty.mkdir()
    summary = run_sensor_sweep(
        git_roots=[str(empty)],
        notes_roots=[str(empty)],
        workspace_roots=[str(empty)],
        window_days=14,
        dry_run=True,
    )
    assert summary["dry_run"] is True
    assert "git" in summary and "notes" in summary and "workspace" in summary
    assert "calendar" not in summary
