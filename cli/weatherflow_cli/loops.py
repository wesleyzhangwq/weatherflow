"""``wf loops`` — run full daily or weekly orchestration (not reflection-only)."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from weatherflow_cli import api

console = Console()

app = typer.Typer(help="Full state + reflection + planning loops.", no_args_is_help=True)


@app.command("daily")
def run_daily(session_id: str = typer.Option("default", "--session-id")) -> None:
    """POST /api/loops/daily — same as the scheduled evening job (without drain in HTTP)."""
    with console.status("Running daily loop…", spinner="dots"):
        try:
            data = api.post("/api/loops/daily", params={"session_id": session_id})
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
    console.print(json.dumps(data, ensure_ascii=False, indent=2))


@app.command("weekly")
def run_weekly(session_id: str = typer.Option("default", "--session-id")) -> None:
    """POST /api/loops/weekly — full weekly review loop."""
    with console.status("Running weekly loop…", spinner="dots"):
        try:
            data = api.post("/api/loops/weekly", params={"session_id": session_id})
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
    console.print(json.dumps(data, ensure_ascii=False, indent=2))
