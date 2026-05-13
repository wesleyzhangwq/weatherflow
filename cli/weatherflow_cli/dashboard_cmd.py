"""``wf dashboard`` — open the Next.js dev URL in your default browser."""

from __future__ import annotations

import os
import webbrowser

import typer
from rich.console import Console

from weatherflow_cli.paths import dashboard_port_from_env, load_root_dotenv, project_root

console = Console()


def run(
    url: str = typer.Option(
        "",
        "--url",
        "-u",
        help="Override URL (default: WF_DASHBOARD_URL or http://127.0.0.1:3000).",
    ),
) -> None:
    load_root_dotenv()
    target = (url or os.environ.get("WF_DASHBOARD_URL") or "").strip()
    if not target:
        port = dashboard_port_from_env()
        target = f"http://127.0.0.1:{port}"
    opened = webbrowser.open(target)
    if opened:
        console.print(f"[green]Opened[/green] {target}")
    else:
        console.print(
            f"[yellow]Could not open a browser automatically.[/yellow] Open manually:\n  {target}"
        )
    console.print(
        f"[dim]Tip: run [bold]npm run dev[/bold] in {project_root() / 'frontend'} if the page does not load.[/dim]"
    )
