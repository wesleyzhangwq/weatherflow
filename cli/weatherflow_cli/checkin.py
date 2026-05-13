"""``wf checkin`` — interactive 1–3 minute morning check-in."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from weatherflow_cli import api

console = Console()


def run(
    skip_intro: bool = typer.Option(False, "--quiet", "-q", help="skip the intro panel"),
) -> None:
    if not skip_intro:
        console.print(
            Panel.fit(
                "[bold]Morning check-in.[/bold]\nFour short questions. 1–3 minutes.\n"
                "Press [dim]Enter[/dim] to skip any field.",
                border_style="cyan",
            )
        )

    status = Prompt.ask("How is today, in one line?", default="")
    did_today = Prompt.ask("What did you actually do?", default="")
    stuck_on = Prompt.ask("What is stuck right now?", default="")
    anxiety = Prompt.ask("What's on your mind / what are you anxious about?", default="")

    payload = {
        "status": status or None,
        "did_today": did_today or None,
        "stuck_on": stuck_on or None,
        "anxiety": anxiety or None,
    }

    with console.status("Listening, reflecting…", spinner="dots"):
        try:
            data = api.post("/api/checkin", json=payload)
        except Exception as exc:
            console.print(f"[red]Could not reach backend at {api.api_base()}: {exc}[/red]")
            raise typer.Exit(code=1)

    state = data["state"]
    refl = data["reflection"]
    suggestion = data.get("suggestion", "")

    weather = state.get("weather_label", "Confusion")
    label_emoji = {
        "Momentum": "?",
        "Confusion": "?",
        "Burnout": "??",
        "Overload": "?",
        "Recovery": "??",
    }.get(weather, "·")

    console.print()
    console.print(
        Panel.fit(
            f"[bold]{label_emoji}  {weather}[/bold]   "
            f"focus={state['focus']} momentum={state['momentum']} "
            f"burnout={state['burnout']} stress={state['stress']}\n"
            f"[dim]{state.get('rationale') or ''}[/dim]",
            title="Today's weather",
            border_style="green",
        )
    )

    console.print()
    console.print(Panel(refl["content"].strip(), title="Reflection", border_style="magenta"))

    if suggestion:
        console.print()
        console.print(Panel(suggestion.strip(), title="One gentle thought", border_style="yellow"))
