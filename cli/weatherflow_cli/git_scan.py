"""``wf scan-git`` — behavior sensor for git activity.

Walks one level under each ``--root`` directory, summarises commit frequency,
project switching, and posts one row per repo to ``/api/sensors/git``.

WeatherFlow's CLI is **not** an automation tool. It is a behavior sensor that
helps the agent see real-world coding rhythm.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from weatherflow_cli import api

console = Console()


@dataclass
class _Stat:
    repo: Path
    commits: int


def _is_git(p: Path) -> bool:
    return (p / ".git").exists()


def _commits_since(repo: Path, days: int) -> int:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", f"--since={days} days ago", "--pretty=oneline"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return 0
    return sum(1 for ln in out.splitlines() if ln.strip())


def run(
    root: List[Path] = typer.Option(
        [Path.home() / "Projects"],
        "--root",
        "-r",
        help="One or more project root dirs to scan (one level deep).",
    ),
    window: int = typer.Option(14, "--window", help="window in days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="don't post to backend"),
) -> None:
    repos: list[Path] = []
    for r in root:
        if not r.exists():
            console.print(f"[yellow]skip missing root: {r}[/yellow]")
            continue
        if _is_git(r):
            repos.append(r)
            continue
        for child in sorted(r.iterdir()):
            if child.is_dir() and _is_git(child):
                repos.append(child)

    if not repos:
        console.print("[red]No git repos found under the given roots.[/red]")
        raise typer.Exit(1)

    stats = [_Stat(repo=p, commits=_commits_since(p, window)) for p in repos]
    active = [s for s in stats if s.commits > 0]
    project_count = len(active)

    table = Table(title=f"Git activity (last {window}d)")
    table.add_column("repo", overflow="fold")
    table.add_column("commits", justify="right")
    for s in stats:
        table.add_row(str(s.repo), str(s.commits))
    console.print(table)

    if not active:
        console.print("[dim]Nothing to send. Quiet weeks are fine.[/dim]")
        return

    switch_score = (
        (project_count - 1) / max(1, len(stats) - 1) if len(stats) > 1 else 0.0
    )

    sent = 0
    for s in active:
        payload = {
            "repo": str(s.repo),
            "commit_count": int(s.commits),
            "project_count": int(project_count),
            "switch_score": round(switch_score, 3),
            "window_days": int(window),
        }
        if dry_run:
            console.print(f"[dim]would POST {payload}[/dim]")
            continue
        try:
            api.post("/api/sensors/git", json=payload)
            sent += 1
        except Exception as exc:
            console.print(f"[red]post failed for {s.repo}: {exc}[/red]")

    if not dry_run:
        console.print(f"[green]sent {sent} record(s) to {api.api_base()}[/green]")
