"""``wf`` command — typer entrypoint."""

from __future__ import annotations

import typer

from weatherflow_cli import setup_calendar as setup_calendar_cmd
from weatherflow_cli import start_cmd
from weatherflow_cli import stop_cmd

app = typer.Typer(
    help="WeatherFlow — rhythm coach + daily cockpit.",
    no_args_is_help=True,
    add_completion=False,
)

app.command(
    name="start",
    help="Start API + Next.js dev server (--detach for background; --api-only for uvicorn only).",
)(start_cmd.run)
app.command(
    name="stop",
    help="Stop dev API + Next.",
)(stop_cmd.run)
app.command(
    name="setup-calendar",
    help="Authorize Google Calendar (OAuth flow → token file).",
)(setup_calendar_cmd.run)


if __name__ == "__main__":
    app()
