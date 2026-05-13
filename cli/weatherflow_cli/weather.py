"""``wf weather`` — print current life weather."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from weatherflow_cli import api

console = Console()


_LABEL_EMOJI = {
    "Momentum": "?",
    "Confusion": "?",
    "Burnout": "??",
    "Overload": "?",
    "Recovery": "??",
}


def run() -> None:
    try:
        state = api.get("/api/state/current")
    except Exception:
        console.print(
            "[yellow]No state yet. Try [bold]wf checkin[/bold] first.[/yellow]"
        )
        raise typer.Exit(code=1)

    label = state.get("weather_label", "Confusion")
    emoji = _LABEL_EMOJI.get(label, "·")
    console.print(
        Panel.fit(
            f"[bold]{emoji}  {label}[/bold]   "
            f"focus={state['focus']} momentum={state['momentum']} "
            f"burnout={state['burnout']} stress={state['stress']} "
            f"confidence={state['confidence']} motivation={state['motivation']}\n"
            f"[dim]{state.get('rationale') or ''}[/dim]",
            title="Life weather",
            border_style="cyan",
        )
    )
