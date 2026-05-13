"""``wf reflect`` — show / generate today's reflection."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from weatherflow_cli import api

console = Console()


def run(
    run_now: bool = typer.Option(False, "--run", help="generate a fresh reflection now"),
    weekly: bool = typer.Option(False, "--weekly", help="weekly review instead of daily"),
) -> None:
    kind = "weekly" if weekly else "daily"

    if run_now:
        with console.status("Reflecting…", spinner="dots"):
            try:
                data = api.post("/api/reflection/run", params={"kind": kind})
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1)
        _print(data, title=f"Fresh {kind} reflection")
        return

    items = api.get("/api/reflection", params={"limit": 1, "kind": kind})
    if not items:
        console.print("[dim]No reflections yet. Try [bold]wf reflect --run[/bold].[/dim]")
        raise typer.Exit(0)
    _print(items[0], title=f"Latest {kind} reflection")


def _print(item: dict, *, title: str) -> None:
    body = (item.get("content") or "").strip() or "[dim](empty)[/dim]"
    console.print(Panel(body, title=f"{title}  —  {item.get('date','')}", border_style="magenta"))
