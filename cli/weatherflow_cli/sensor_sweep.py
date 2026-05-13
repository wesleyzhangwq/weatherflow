"""``wf sensors`` — run all behavior sensors in one request (git + notes + workspace)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.json import JSON

from weatherflow_cli import api

console = Console()


def run(
    git_root: Optional[List[Path]] = typer.Option(
        None,
        "--git-root",
        "-g",
        help="Repeat for each git scan root (default: server env or ~/Projects).",
    ),
    notes_root: Optional[List[Path]] = typer.Option(
        None,
        "--notes-root",
        "-n",
        help="Repeat for each notes vault root (default: server env or ~/Notes).",
    ),
    workspace_root: Optional[List[Path]] = typer.Option(
        None,
        "--workspace-root",
        "-w",
        help="Repeat for each workspace scan root (default: server env or ~/Projects).",
    ),
    window: int = typer.Option(14, "--window", help="window in days for all sensors"),
    dry_run: bool = typer.Option(False, "--dry-run", help="plan only; no DB writes"),
) -> None:
    gr = git_root or []
    nr = notes_root or []
    wr = workspace_root or []
    payload: dict = {
        "git_roots": [str(p.expanduser()) for p in gr],
        "notes_roots": [str(p.expanduser()) for p in nr],
        "workspace_roots": [str(p.expanduser()) for p in wr],
        "window_days": window,
        "dry_run": dry_run,
    }
    with console.status("Running sensor sweep…", spinner="dots"):
        try:
            summary = api.post("/api/sensors/sweep", json=payload)
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
    console.print(JSON.from_data(summary))
    if not dry_run:
        console.print(f"[green]Done. State refreshed once at {api.api_base()}[/green]")
