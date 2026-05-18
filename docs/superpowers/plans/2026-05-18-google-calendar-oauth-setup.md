# Google Calendar OAuth Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `wf setup-calendar` and backend token-file support so Google Calendar Dev Review can use refreshable local OAuth credentials.

**Architecture:** The CLI owns the browser-based installed-app OAuth flow and writes a token JSON file. The backend Calendar connector loads that token file, refreshes expired credentials when possible, and falls back to the existing access-token env path for temporary debugging.

**Tech Stack:** Typer, google-auth, google-auth-oauthlib, Google OAuth Desktop app flow, FastAPI settings, existing httpx Calendar connector.

---

## Task 1: Dependencies and Config

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `.env.example`

Steps:

1. Add CLI dependencies: `google-auth>=2.30,<3.0`, `google-auth-oauthlib>=1.2,<2.0`.
2. Add backend dependency: `google-auth>=2.30,<3.0`.
3. Add backend setting:
   `google_calendar_token_file: str = Field(default="", alias="GOOGLE_CALENDAR_TOKEN_FILE")`
4. Add `.env.example` line under Dev Review providers:
   `GOOGLE_CALENDAR_TOKEN_FILE=`
5. Run `uv lock`.
6. Run `make check`.
7. Commit: `chore: add google calendar oauth dependencies`.

## Task 2: CLI Setup Calendar

**Files:**
- Create: `cli/weatherflow_cli/setup_calendar.py`
- Modify: `cli/weatherflow_cli/__main__.py`
- Test: add or update CLI-focused tests if the project has a CLI test pattern; otherwise verify help and ruff.

Implementation:

- Constants:
  `SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]`
- Helper `default_token_path() -> Path`:
  uses `DATA_DIR` env if set; else `~/.local/share/weatherflow/data`.
- Command:
  `run(credentials: Path, token_path: Optional[Path], calendar_id: str = "primary")`
- Validate credentials path exists.
- Use:
  `InstalledAppFlow.from_client_secrets_file(str(credentials), SCOPES)`
  then `flow.run_local_server(port=0)`.
- Create parent directories for token path.
- Write `creds.to_json()` to token path.
- Print `.env` guidance for `GOOGLE_CALENDAR_TOKEN_FILE` and `GOOGLE_CALENDAR_CALENDAR_ID`.
- Register as `wf setup-calendar`.

Verification:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run wf setup-calendar --help
UV_CACHE_DIR=/private/tmp/uv-cache uv run --package weatherflow-backend --extra dev ruff check cli/weatherflow_cli
```

Commit: `feat: add calendar oauth setup cli`.

## Task 3: Backend Token File Credentials

**Files:**
- Modify: `backend/app/mcp/google_calendar.py`
- Modify: `backend/app/routers/dev_review.py`
- Modify: `backend/tests/test_dev_review_providers.py`
- Modify: `backend/tests/test_dev_review_api.py`

Implementation:

- Add `SCOPES`.
- Add helper `resolve_calendar_token_file(settings) -> str`.
- Add helper `load_calendar_access_token(token_file, fallback_access_token) -> str | None`.
- If token file exists:
  - `Credentials.from_authorized_user_file(token_file, SCOPES)`
  - if valid: return `creds.token`
  - if expired and refresh_token: refresh with `Request()`, write `creds.to_json()` back, return token
  - if invalid and not refreshable: return fallback if present
- Update `GoogleCalendarConnector` to accept either `access_token` or `token_file`; keep direct access token fallback.
- Update `create_dev_review_run` to construct Calendar connector from token file when available.
- Update provider readiness: Calendar ready if token file exists or access token env exists.

Tests:

- readiness ready with token file env pointing at an existing file.
- readiness ready with default token file under `DATA_DIR`.
- connector uses token-file bearer token.
- expired token refresh writes updated JSON; monkeypatch refresh to avoid network.
- invalid/missing file falls back to access token.

Run:

```bash
cd backend && UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/test_dev_review_api.py tests/test_dev_review_providers.py -q
```

Commit: `feat: use calendar oauth token file`.

## Task 4: Docs and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` if needed

Docs:

- Add setup example:
  `uv run wf setup-calendar --credentials ./credentials.json`
- Explain Google Cloud prerequisite: Calendar API enabled, OAuth Desktop client JSON downloaded.
- Explain token file is local and refreshable.
- Keep `GOOGLE_CALENDAR_ACCESS_TOKEN` described as temporary fallback.

Verification:

```bash
make check
git status --short
```

Commit: `docs: document calendar oauth setup`.

## Self-Review Notes

- Scope stays local-first and CLI-only.
- No hosted OAuth callback or dashboard auth UI.
- Backend continues to sanitize Calendar event payloads.
- Access-token env remains as a fallback, not the primary path.
