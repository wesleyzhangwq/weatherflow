"""Dev Review Agent Run CLI."""

from __future__ import annotations

from typing import Any

import typer

from weatherflow_cli import api


def run(
    days: int = typer.Option(7, "--days", min=1, max=31, help="Review window in days."),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Show latest saved review instead of running a new one.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Show Dev Review provider readiness without running a review.",
    ),
) -> None:
    try:
        if check:
            data = api.get("/api/dev-review/providers")
            _print_provider_check(data)
            return
        if latest:
            data = api.get("/api/dev-review/runs/latest")
            if data is None:
                typer.echo("No dev review has been saved yet.")
                return
        else:
            data = api.post("/api/dev-review/runs", json={"window_days": days})
    except Exception as exc:
        typer.echo(f"Dev review failed: {exc}")
        raise typer.Exit(code=1) from exc

    _print_review(data)


def _print_review(data: dict[str, Any]) -> None:
    typer.echo(f"Dev Weather: {_text(data.get('dev_weather'))}")
    typer.echo("")
    typer.echo("Summary")
    typer.echo(_text(data.get("summary")))
    typer.echo("")
    _section("Main Work Threads", data.get("main_work_threads") or [])
    _section("Shipping Progress", data.get("shipping_progress") or [])
    _section("Collaboration Load", data.get("collaboration_load") or [])
    _section("Meeting Load", data.get("meeting_load") or [])
    _section("Rhythm Risks", data.get("rhythm_risks") or [])
    typer.echo("Next Week Suggestion")
    typer.echo(_text(data.get("next_week_suggestion")))
    typer.echo("")
    typer.echo("Source Coverage")
    _source_coverage(data.get("source_coverage") or {})
    _trace(data.get("run") or {})


def _print_provider_check(items: list[dict[str, Any]]) -> None:
    typer.echo("Dev Review Providers")
    if not items:
        typer.echo("-")
        return
    for item in items:
        typer.echo(
            f"- {_text(item.get('label') or item.get('name'))}: "
            f"{_text(item.get('status'))} ({_text(item.get('required_env'))})"
        )


def _section(title: str, items: list[Any]) -> None:
    typer.echo(title)
    if not items:
        typer.echo("-")
    for item in items:
        typer.echo(f"- {_text(item)}")
    typer.echo("")


def _source_coverage(coverage: dict[str, Any]) -> None:
    if not coverage:
        typer.echo("-")
        return

    for name, value in coverage.items():
        if isinstance(value, dict):
            status = _text(value.get("status"))
            summary = _text(value.get("summary"), default="")
            if summary:
                typer.echo(f"- {name}: {status} — {summary}")
            else:
                typer.echo(f"- {name}: {status}")
        else:
            typer.echo(f"- {name}: {_text(value)}")


def _trace(run_data: dict[str, Any]) -> None:
    if run_data.get("status") != "partial":
        return

    typer.echo("")
    typer.echo("Trace")
    for step in run_data.get("steps") or []:
        typer.echo(
            f"- {_text(step.get('name'))}: {_text(step.get('status'))} — "
            f"{_text(step.get('summary'))}"
        )


def _text(value: Any, *, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return str(value)
