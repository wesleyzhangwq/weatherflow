# Google Calendar OAuth Setup CLI Design

Date: 2026-05-18

## Goal

Make Google Calendar usable in WeatherFlow without manually copying short-lived
access tokens. Add a local CLI setup flow that authorizes Google Calendar,
stores a refreshable token file, and lets the backend use that token file for
Dev Review runs.

This follows Google's documented desktop / installed-app OAuth pattern and the
Calendar Python quickstart: a desktop OAuth client `credentials.json` starts a
browser-based local authorization flow and creates a local token file containing
access and refresh tokens.

References:

- Google Calendar Python quickstart:
  `https://developers.google.com/workspace/calendar/api/quickstart/python`
- Google OAuth for desktop apps:
  `https://developers.google.com/identity/protocols/oauth2/native-app`

## Non-goals

- Do not create a hosted OAuth callback service.
- Do not create Google Cloud OAuth clients automatically.
- Do not support multiple Google accounts in the first version.
- Do not store refresh tokens in SQLite.
- Do not add a dashboard OAuth UI.
- Do not remove `GOOGLE_CALENDAR_ACCESS_TOKEN`; keep it as a temporary fallback.

## User Flow

The user creates a Google OAuth Desktop client in Google Cloud Console, downloads
the client JSON, then runs:

```bash
uv run wf setup-calendar --credentials ./credentials.json
```

The CLI:

1. Starts the installed-app OAuth flow in the user's browser.
2. Requests only Calendar readonly scope.
3. Stores the authorized token JSON locally.
4. Prints the token path and `.env` values to use.

Default token path:

```text
${DATA_DIR}/google_calendar_token.json
```

If `DATA_DIR` is not set, this resolves to:

```text
~/.local/share/weatherflow/data/google_calendar_token.json
```

## Configuration

Add:

```env
GOOGLE_CALENDAR_TOKEN_FILE=
GOOGLE_CALENDAR_CALENDAR_ID=primary
```

Rules:

- Backend Calendar connector prefers `GOOGLE_CALENDAR_TOKEN_FILE` when present.
- If the token file path is empty, backend uses the default token path under
  `DATA_DIR`.
- If no token file exists, backend falls back to `GOOGLE_CALENDAR_ACCESS_TOKEN`.
- Provider readiness reports Calendar as ready when either a token file exists
  or `GOOGLE_CALENDAR_ACCESS_TOKEN` is configured.

## Backend Token Handling

The backend should load token-file credentials with Calendar readonly scope.

Behavior:

- Valid token: use it directly.
- Expired token with refresh token: refresh and write the updated token JSON
  back to the same path.
- Invalid or missing token file: fall back to access-token env if present;
  otherwise provider is not ready.

The Calendar connector must continue to sanitize event data exactly as before:
title, start, duration, calendar name, derived category only. It must not store
descriptions, attendee emails, links, locations, attachments, or organizer
identity.

## CLI Details

Add command:

```bash
uv run wf setup-calendar \
  --credentials ./credentials.json \
  --token-path ~/.local/share/weatherflow/data/google_calendar_token.json \
  --calendar-id primary
```

Options:

- `--credentials`: path to Google OAuth Desktop client JSON. Required.
- `--token-path`: optional output path. Defaults to WeatherFlow data dir token.
- `--calendar-id`: optional, defaults to `primary`.

Output:

```text
Google Calendar authorization complete.
Token saved to: ...

Add or confirm these values in .env:
GOOGLE_CALENDAR_TOKEN_FILE=...
GOOGLE_CALENDAR_CALENDAR_ID=primary
```

## Testing Scope

CLI:

- Default token path resolves under `DATA_DIR`.
- Setup writes credentials JSON returned by a mocked installed-app flow.
- Missing credentials path exits with a clear error.

Backend:

- Readiness is ready when token file exists.
- Readiness still works with `GOOGLE_CALENDAR_ACCESS_TOKEN` fallback.
- Connector loads token-file credentials and uses bearer token.
- Expired credentials with refresh token are refreshed and persisted.
- Missing/invalid token file falls back to access-token env when present.

Docs:

- `.env.example` documents token-file configuration.
- README documents the setup command and high-level Google Cloud prerequisite.
