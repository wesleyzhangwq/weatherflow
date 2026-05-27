"""Google Calendar OAuth setup for local Dev Review context."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from google_auth_oauthlib.flow import InstalledAppFlow

# calendar.events: read + create + modify events on calendars the user owns.
# Cannot delete calendars, change settings, or access other users' data.
# This is the minimum scope needed for the Proposal write-tool loop
# (create_focus_block / create_event) to actually take effect on Google.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def default_token_path() -> Path:
    data_dir = os.environ.get("DATA_DIR", "").strip()
    root = (
        Path(os.path.expandvars(data_dir)).expanduser()
        if data_dir
        else Path.home() / ".local/share/weatherflow/data"
    )
    return root / "google_calendar_token.json"


def run(
    credentials: Path = typer.Option(
        ...,
        "--credentials",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Google OAuth Desktop client JSON from Google Cloud Console.",
    ),
    token_path: Optional[Path] = typer.Option(
        None,
        "--token-path",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Where to save the refreshable Google Calendar token JSON.",
    ),
    calendar_id: str = typer.Option(
        "primary",
        "--calendar-id",
        help="Google Calendar ID to use for Dev Review.",
    ),
) -> None:
    output = token_path or default_token_path()
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials), SCOPES)
    creds = flow.run_local_server(port=0)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(creds.to_json(), encoding="utf-8")

    typer.echo("Google Calendar authorization complete.")
    typer.echo(f"Token saved to: {output}")
    typer.echo("")
    typer.echo("Add or confirm these values in .env:")
    typer.echo(f"GOOGLE_CALENDAR_TOKEN_FILE={output}")
    typer.echo(f"GOOGLE_CALENDAR_CALENDAR_ID={calendar_id}")


__all__ = ["default_token_path", "run", "SCOPES"]
