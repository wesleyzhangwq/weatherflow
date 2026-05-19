"""``wf`` command — typer entrypoint."""

from __future__ import annotations

import typer

from weatherflow_cli import checkin as checkin_cmd
from weatherflow_cli import dashboard_cmd
from weatherflow_cli import dev_review as dev_review_cmd
from weatherflow_cli import patterns as patterns_cmd
from weatherflow_cli import reflect as reflect_cmd
from weatherflow_cli import setup_calendar as setup_calendar_cmd
from weatherflow_cli import start_cmd
from weatherflow_cli import stop_cmd
from weatherflow_cli import weather as weather_cmd

app = typer.Typer(
    help="WeatherFlow — long-term growth companion. Low friction. Local first.",
    no_args_is_help=True,
    add_completion=False,
)

app.command(
    name="start",
    help="Start API + Next.js dev server (--detach for background; --api-only for uvicorn only).",
)(start_cmd.run)
app.command(
    name="stop",
    help="Stop dev API + Next (PID file from wf start and/or listen ports).",
)(stop_cmd.run)
app.command(name="dashboard", help="Open the web dashboard in your browser.")(dashboard_cmd.run)
app.command(name="checkin", help="1–3 minute morning check-in. Triggers daily loop.")(checkin_cmd.run)
app.command(name="weather", help="Show today's life weather + state at a glance.")(weather_cmd.run)
app.command(name="reflect", help="Show today's reflection. Use --run to regenerate.")(reflect_cmd.run)
app.command(name="dev-review", help="Run or show the Dev Review Agent.")(dev_review_cmd.run)
app.command(name="setup-calendar", help="Authorize Google Calendar for Dev Review.")(setup_calendar_cmd.run)
app.command(name="patterns", help="Window-vs-window pattern report.")(patterns_cmd.run)


if __name__ == "__main__":
    app()
