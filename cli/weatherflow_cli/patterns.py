"""``wf patterns`` — show window-vs-window pattern report from backend."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from weatherflow_cli import api

console = Console()


_SEV_STYLE = {
    "info": "cyan",
    "watch": "yellow",
    "alert": "red",
}


def run(
    window: int = typer.Option(7, "--window", help="window length in days"),
) -> None:
    try:
        report = api.get("/api/state/patterns", params={"window_days": window})
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    metrics = report.get("metrics", [])
    table = Table(title=f"Metrics — current vs previous {window}d window")
    table.add_column("metric")
    table.add_column("current", justify="right")
    table.add_column("previous", justify="right")
    table.add_column("delta", justify="right")
    table.add_column("?%", justify="right")
    for m in metrics:
        pct = m.get("pct_delta")
        pct_str = f"{pct:+.1f}%" if pct is not None else "—"
        delta = m.get("delta", 0)
        delta_str = f"{delta:+}"
        table.add_row(
            m["name"],
            str(m["current"]),
            str(m["previous"]),
            delta_str,
            pct_str,
        )
    console.print(table)

    patterns = report.get("patterns", [])
    if not patterns:
        console.print("[dim]No notable patterns this window. Quiet weeks are fine.[/dim]")
        return

    for p in patterns:
        style = _SEV_STYLE.get(p.get("severity", "info"), "cyan")
        console.print(
            Panel(
                p.get("explanation", ""),
                title=f"[{style}]{p.get('label','')}[/{style}]  ({p.get('code','')})",
                border_style=style,
            )
        )
