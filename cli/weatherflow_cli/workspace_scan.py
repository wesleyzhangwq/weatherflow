"""``wf scan-workspace`` — filesystem activity / project fragmentation sensor."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import typer
from rich.console import Console
from rich.table import Table

from weatherflow_cli import api

console = Console()

_SKIP = {".git", "node_modules", ".venv", "venv", "dist", "build", ".idea", "__pycache__"}


def run(
    root: List[Path] = typer.Option(
        [Path.home() / "Projects"],
        "--root",
        "-r",
        help="Directories to scan (non-git aggregate).",
    ),
    window: int = typer.Option(7, "--window", help="activity window in days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="don't POST to backend"),
) -> None:
    cutoff = time.time() - window * 86400

    for r in root:
        if not r.exists():
            console.print(f"[yellow]skip missing root: {r}[/yellow]")
            continue
        r = r.resolve()
        project_mtimes: dict[str, float] = {}
        touched = 0

        for p in r.rglob("*"):
            if not p.is_file():
                continue
            if _SKIP & set(p.parts):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            touched += 1
            try:
                rel = p.relative_to(r)
            except ValueError:
                continue
            if not rel.parts:
                continue
            proj = rel.parts[0]
            project_mtimes[proj] = max(project_mtimes.get(proj, 0.0), st.st_mtime)

        active = len(project_mtimes)
        frag = round(min(1.0, (active - 1) / 10.0), 3) if active > 1 else 0.0
        top_dirs = [
            k
            for k, _ in sorted(
                project_mtimes.items(), key=lambda kv: kv[1], reverse=True
            )
        ][:16]

        table = Table(title=f"Workspace activity — {r} (last {window}d)")
        table.add_column("metric")
        table.add_column("value", justify="right")
        for k, v in [
            ("touched files", touched),
            ("active top-level areas", active),
            ("fragmentation score", frag),
            ("hot dirs", ", ".join(top_dirs[:8]) or "—"),
        ]:
            table.add_row(str(k), str(v))
        console.print(table)

        payload = {
            "root": str(r),
            "active_project_count": active,
            "touched_paths": touched,
            "fragmentation_score": frag,
            "top_dirs": top_dirs,
            "window_days": window,
        }
        if dry_run:
            console.print(f"[dim]would POST {payload}[/dim]")
            continue
        try:
            api.post("/api/sensors/workspace", json=payload)
            console.print(f"[green]sent workspace scan to {api.api_base()}[/green]")
        except Exception as exc:
            console.print(f"[red]post failed: {exc}[/red]")
