# MCP Provider Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace WeatherFlow's direct GitHub and Google Calendar REST connectors with MCP-backed providers designed around WF's core loops: planning, reminders, review, and project momentum.

**Architecture:** Keep `ProviderContext` and `DevReviewAgent` stable while moving third-party access behind MCP tools. Build local stdio MCP servers first, add a small WF MCP client, then migrate provider calls behind a feature flag before deleting direct connector usage.

**Tech Stack:** Python, FastAPI, `mcp` Python SDK, stdio MCP transport, `httpx`, Google OAuth credentials, GitHub REST API, pytest.

---

## Design Principles

1. **WF-first tools, not full API mirrors.** Tools should model WF jobs: finding usable time, creating focus blocks, reading project status, creating project tasks, and writing project logs.
2. **Calendar equals time commitment.** Calendar tools should help WF understand and shape the user's schedule.
3. **GitHub equals engineering evidence.** GitHub tools should help WF understand project momentum and maintain project artifacts.
4. **Memory remains downstream.** MCP tools do not write long-term memory directly; WF agents decide what belongs in memory.
5. **Direct API mode remains during migration.** The first production path should support both `direct` and `mcp` modes.
6. **Destructive tools require confirmation above the tool layer.** `calendar.delete_event`, `calendar.update_event`, `github.update_issue`, and file writes must be guarded by product-level confirmation flows.

## Target Tool Surface

### Calendar MCP MVP

```text
calendar.search_events
calendar.find_free_slots
calendar.create_event
calendar.create_focus_block
```

### Calendar MCP Post-MVP

```text
calendar.update_event
calendar.delete_event
```

### GitHub MCP MVP

```text
github.get_repo_status
github.get_recent_commits
github.list_issues
github.create_issue
github.get_file
github.create_or_update_file
```

### GitHub MCP Post-MVP

```text
github.list_repos
github.update_issue
github.list_pull_requests
```

## File Structure

### New files

- `backend/app/mcp_client/client.py`
  - Owns MCP stdio sessions, tool listing, typed `call_tool`, timeouts, and error mapping.
- `backend/app/mcp_client/provider_registry.py`
  - Chooses direct or MCP provider mode from settings.
- `backend/app/providers/github_direct.py`
  - Temporary home for current direct GitHub connector logic.
- `backend/app/providers/google_calendar_direct.py`
  - Temporary home for current direct Calendar connector logic.
- `backend/app/providers/github_mcp.py`
  - WF provider wrapper that calls GitHub MCP tools and returns `ProviderContext`.
- `backend/app/providers/google_calendar_mcp.py`
  - WF provider wrapper that calls Calendar MCP tools and returns `ProviderContext`.
- `mcp_servers/weatherflow_github/server.py`
  - Local GitHub MCP server.
- `mcp_servers/weatherflow_github/tools.py`
  - GitHub tool implementations.
- `mcp_servers/weatherflow_github/schemas.py`
  - Tool input/output Pydantic models.
- `mcp_servers/weatherflow_calendar/server.py`
  - Local Calendar MCP server.
- `mcp_servers/weatherflow_calendar/tools.py`
  - Calendar tool implementations.
- `mcp_servers/weatherflow_calendar/schemas.py`
  - Tool input/output Pydantic models.
- `mcp_servers/shared/provider_context.py`
  - Shared serialization helpers for MCP results that map to WF `ProviderContext`.
- `backend/tests/test_mcp_client.py`
  - MCP client unit tests with fake stdio server/session.
- `backend/tests/test_github_mcp_provider.py`
  - WF GitHub MCP provider tests.
- `backend/tests/test_calendar_mcp_provider.py`
  - WF Calendar MCP provider tests.
- `backend/tests/test_mcp_provider_mode.py`
  - Router/provider mode selection tests.
- `mcp_servers/tests/test_github_tools.py`
  - GitHub MCP server tool tests.
- `mcp_servers/tests/test_calendar_tools.py`
  - Calendar MCP server tool tests.
- `docs/MCP_PROVIDER_ARCHITECTURE.md`
  - Human-readable architecture and tool contract docs.

### Modified files

- `pyproject.toml`
  - Add MCP server packages and test paths if needed.
- `uv.lock`
  - Update after adding the MCP SDK.
- `backend/app/config.py`
  - Add provider mode and MCP command settings.
- `backend/app/routers/dev_review.py`
  - Replace direct connector construction with provider registry.
- `backend/app/routers/mcp.py`
  - Either rename or narrow this router; avoid implying it is the MCP protocol server.
- `backend/app/mcp/github.py`
  - Move or deprecate direct connector code.
- `backend/app/mcp/google_calendar.py`
  - Move or deprecate direct connector code.
- `.env.example`
  - Add `DEV_REVIEW_PROVIDER_MODE`, MCP server command examples, and safety notes.
- `README.md`
  - Replace "GitHub MCP + Google Calendar MCP" wording with accurate MCP-backed provider wording after migration.

## Tool Contracts

### `calendar.search_events`

Input:

```json
{
  "start_time": "2026-05-22T09:00:00+08:00",
  "end_time": "2026-05-22T18:00:00+08:00",
  "keyword": "review",
  "calendar_id": "primary",
  "max_results": 50
}
```

Output:

```json
{
  "events": [
    {
      "id": "calendar-event-id",
      "title": "Design review",
      "start": "2026-05-22T10:00:00+08:00",
      "end": "2026-05-22T10:30:00+08:00",
      "duration_minutes": 30,
      "category": "review"
    }
  ],
  "coverage": {
    "calendar_id": "primary",
    "event_count": 1
  }
}
```

### `calendar.find_free_slots`

Input:

```json
{
  "start_time": "2026-05-22T09:00:00+08:00",
  "end_time": "2026-05-22T18:00:00+08:00",
  "min_duration_minutes": 45,
  "calendar_id": "primary",
  "workday_start": "09:00",
  "workday_end": "18:00"
}
```

Output:

```json
{
  "slots": [
    {
      "start": "2026-05-22T14:00:00+08:00",
      "end": "2026-05-22T15:30:00+08:00",
      "duration_minutes": 90
    }
  ]
}
```

### `calendar.create_event`

Input:

```json
{
  "title": "Project planning",
  "start_time": "2026-05-23T10:00:00+08:00",
  "end_time": "2026-05-23T11:00:00+08:00",
  "calendar_id": "primary",
  "description": "Created by WeatherFlow",
  "dry_run": false
}
```

Output:

```json
{
  "created": true,
  "event": {
    "id": "calendar-event-id",
    "title": "Project planning",
    "html_link": "https://calendar.google.com/..."
  }
}
```

### `calendar.create_focus_block`

Input:

```json
{
  "title": "Deep Work: WF memory refactor",
  "duration_minutes": 90,
  "preferred_time": "morning",
  "priority": "high",
  "date": "2026-05-23",
  "calendar_id": "primary",
  "dry_run": false
}
```

Output:

```json
{
  "created": true,
  "selected_slot": {
    "start": "2026-05-23T10:00:00+08:00",
    "end": "2026-05-23T11:30:00+08:00"
  },
  "event": {
    "id": "calendar-event-id",
    "title": "Deep Work: WF memory refactor"
  }
}
```

### `github.get_repo_status`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "window_days": 7
}
```

Output:

```json
{
  "repo": "wesleyzhangwq/weatherflow",
  "default_branch": "main",
  "latest_commit": {
    "sha": "abc123",
    "message": "Update provider docs",
    "committed_at": "2026-05-22T08:30:00Z"
  },
  "open_issues_count": 4,
  "open_prs_count": 1,
  "recent_activity": [
    {
      "type": "commit",
      "title": "Update provider docs",
      "at": "2026-05-22T08:30:00Z"
    }
  ]
}
```

### `github.get_recent_commits`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "branch": "main",
  "since": "2026-05-15T00:00:00Z",
  "limit": 30
}
```

Output:

```json
{
  "commits": [
    {
      "sha": "abc123",
      "message": "Refine calendar setup",
      "author": "Wesley Zhang",
      "committed_at": "2026-05-22T08:30:00Z"
    }
  ]
}
```

### `github.list_issues`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "state": "open",
  "labels": ["wf"],
  "limit": 50
}
```

Output:

```json
{
  "issues": [
    {
      "number": 12,
      "title": "Refactor memory retrieval pipeline",
      "state": "open",
      "labels": ["wf"],
      "updated_at": "2026-05-22T08:30:00Z",
      "url": "https://github.com/..."
    }
  ]
}
```

### `github.create_issue`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "title": "Refactor memory retrieval pipeline",
  "body": "Created from WeatherFlow check-in.",
  "labels": ["wf", "memory"],
  "dry_run": false
}
```

Output:

```json
{
  "created": true,
  "issue": {
    "number": 13,
    "title": "Refactor memory retrieval pipeline",
    "url": "https://github.com/..."
  }
}
```

### `github.get_file`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "path": "README.md",
  "ref": "main",
  "max_bytes": 50000
}
```

Output:

```json
{
  "path": "README.md",
  "sha": "blob-sha",
  "content": "# WeatherFlow\n...",
  "truncated": false
}
```

### `github.create_or_update_file`

Input:

```json
{
  "owner": "wesleyzhangwq",
  "repo": "weatherflow",
  "path": "docs/project-log.md",
  "content": "# Project Log\n...",
  "message": "docs: update project log from WeatherFlow",
  "branch": "main",
  "expected_sha": "existing-blob-sha",
  "dry_run": false
}
```

Output:

```json
{
  "updated": true,
  "commit": {
    "sha": "commit-sha",
    "url": "https://github.com/..."
  }
}
```

## Current Implementation Reuse Map

The existing direct API implementation should not be thrown away. It already contains the most valuable parts for the MCP migration:

- `backend/app/mcp/github.py`
  - Reuse the GitHub auth/env handling, recent activity parsing, repo status summarization, and `normalize_github_summary`.
  - Move this code into `backend/app/providers/github_direct.py` first, then copy the stable HTTP client pieces into `mcp_servers/weatherflow_github/tools.py`.
- `backend/app/mcp/google_calendar.py`
  - Reuse OAuth token loading/refresh, Calendar REST event parsing, date-range handling, and readiness checks.
  - Move this code into `backend/app/providers/google_calendar_direct.py` first, then reuse the Calendar client helpers inside `mcp_servers/weatherflow_calendar/tools.py`.
- `backend/app/memory/schemas.py`
  - Keep `ProviderContext` as the backend-facing shape for Dev Review.
  - MCP tools should return tool-specific JSON; MCP provider wrappers translate that JSON into `ProviderContext`.
- `backend/app/agents/dev_review_agent.py`
  - Treat Dev Review as a core product feature, not as a demo consumer.
  - Do not rewrite the agent until the provider boundary is stable.
- `backend/app/routers/dev_review.py`
  - This is the first integration point for MCP-backed read tools.
  - Later, planning/check-in routes can use action proposals for Calendar events and GitHub issues.

## Product Loop Target

The migration should make this loop explicit in code:

```text
check-in
  -> analyze user state and project pressure
  -> search calendar + read GitHub evidence through MCP
  -> generate a concrete plan
  -> propose focus block and/or GitHub issue
  -> execute only after confirmation
  -> evening review
  -> update memory
```

This means the MCP layer stays intentionally boring: it exposes reliable tools. WF remains the product brain that decides when those tools matter.

## Environment Contract

Add:

```bash
DEV_REVIEW_PROVIDER_MODE=direct
WF_GITHUB_MCP_COMMAND=uv run python -m mcp_servers.weatherflow_github.server
WF_CALENDAR_MCP_COMMAND=uv run python -m mcp_servers.weatherflow_calendar.server
WF_MCP_TOOL_TIMEOUT_SECONDS=20
WF_MCP_WRITE_TOOLS_ENABLED=false
```

Modes:

- `direct`: current behavior.
- `mcp`: use MCP tools only.
- `dual`: call MCP and direct providers, compare results, return direct result. Use this for migration confidence.

## Phase 1: Move Direct Connectors Without Behavior Change

### Task 1: Create provider package and move direct GitHub connector

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/github_direct.py`
- Modify: `backend/app/mcp/github.py`
- Modify: `backend/app/routers/dev_review.py`
- Test: `backend/tests/test_dev_review_providers.py`

- [ ] Copy `GithubConnector`, `_parse_dt`, and `normalize_github_summary` from `backend/app/mcp/github.py` to `backend/app/providers/github_direct.py`.
- [ ] Leave `backend/app/mcp/github.py` as a compatibility import shim:

```python
from app.providers.github_direct import GithubConnector, normalize_github_summary

__all__ = ["GithubConnector", "normalize_github_summary"]
```

- [ ] Update imports in `backend/app/routers/dev_review.py` to use `app.providers.github_direct`.
- [ ] Run:

```bash
uv run --package weatherflow-backend --extra dev pytest backend/tests/test_dev_review_providers.py -q
```

Expected: existing tests pass.

- [ ] Commit:

```bash
git add backend/app/providers backend/app/mcp/github.py backend/app/routers/dev_review.py backend/tests/test_dev_review_providers.py
git commit -m "refactor: move github direct provider"
```

### Task 2: Create provider package and move direct Calendar connector

**Files:**
- Create: `backend/app/providers/google_calendar_direct.py`
- Modify: `backend/app/mcp/google_calendar.py`
- Modify: `backend/app/routers/dev_review.py`
- Test: `backend/tests/test_dev_review_providers.py`

- [ ] Copy `GoogleCalendarConnector`, token helpers, event sanitizers, and calendar helper functions to `backend/app/providers/google_calendar_direct.py`.
- [ ] Leave `backend/app/mcp/google_calendar.py` as a compatibility import shim.
- [ ] Update imports in `backend/app/routers/dev_review.py` to use `app.providers.google_calendar_direct`.
- [ ] Run:

```bash
uv run --package weatherflow-backend --extra dev pytest backend/tests/test_dev_review_providers.py -q
```

Expected: existing Calendar tests pass.

- [ ] Commit:

```bash
git add backend/app/providers backend/app/mcp/google_calendar.py backend/app/routers/dev_review.py backend/tests/test_dev_review_providers.py
git commit -m "refactor: move calendar direct provider"
```

## Phase 2: Add MCP Server Packages

### Task 3: Add MCP SDK dependency and package entry points

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `mcp_servers/__init__.py`
- Create: `mcp_servers/weatherflow_github/__init__.py`
- Create: `mcp_servers/weatherflow_calendar/__init__.py`
- Create: `mcp_servers/shared/__init__.py`

- [ ] Add MCP Python SDK dependency:

```bash
uv add --package weatherflow-backend mcp
```

- [ ] Create empty package marker files.
- [ ] Run:

```bash
uv run python -c "import mcp; print('mcp ok')"
```

Expected: prints `mcp ok`.

- [ ] Commit:

```bash
git add pyproject.toml uv.lock mcp_servers
git commit -m "chore: add mcp server packages"
```

### Task 4: Define shared MCP output helpers

**Files:**
- Create: `mcp_servers/shared/provider_context.py`
- Test: `mcp_servers/tests/test_provider_context.py`

- [ ] Add helper that converts `ProviderContext` to plain JSON-safe dict.
- [ ] Add helper that validates MCP tool dict output has `source`, `status`, `window_days`, `signals`, `coverage`, and `warnings`.
- [ ] Tests should assert that Pydantic models serialize cleanly and do not leak non-JSON objects.
- [ ] Run:

```bash
uv run --package weatherflow-backend --extra dev pytest mcp_servers/tests/test_provider_context.py -q
```

Expected: tests pass.

- [ ] Commit:

```bash
git add mcp_servers/shared mcp_servers/tests/test_provider_context.py
git commit -m "feat: add provider context mcp serialization"
```

## Phase 3: Implement Calendar MCP Server MVP

### Task 5: Add Calendar MCP schemas

**Files:**
- Create: `mcp_servers/weatherflow_calendar/schemas.py`
- Test: `mcp_servers/tests/test_calendar_schemas.py`

- [ ] Define Pydantic models for:
  - `CalendarSearchEventsInput`
  - `CalendarFindFreeSlotsInput`
  - `CalendarCreateEventInput`
  - `CalendarCreateFocusBlockInput`
  - `CalendarEventRead`
  - `CalendarFreeSlot`
- [ ] Validate `end_time > start_time`.
- [ ] Validate `duration_minutes > 0`.
- [ ] Validate `preferred_time` is `morning`, `afternoon`, or `evening`.
- [ ] Run schema tests.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/schemas.py mcp_servers/tests/test_calendar_schemas.py
git commit -m "feat: define calendar mcp schemas"
```

### Task 6: Implement `calendar.search_events`

**Files:**
- Create: `mcp_servers/weatherflow_calendar/tools.py`
- Test: `mcp_servers/tests/test_calendar_tools.py`

- [ ] Reuse:
  - `load_calendar_access_token`
  - `_calendar_path`
  - `sanitize_calendar_events`
- [ ] Implement `search_events` against `/calendars/{calendar_id}/events`.
- [ ] Support optional keyword filtering after sanitization.
- [ ] Test with mocked `httpx.AsyncClient.get`.
- [ ] Run:

```bash
uv run --package weatherflow-backend --extra dev pytest mcp_servers/tests/test_calendar_tools.py::test_search_events -q
```

- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/tools.py mcp_servers/tests/test_calendar_tools.py
git commit -m "feat: add calendar search events mcp tool"
```

### Task 7: Implement `calendar.find_free_slots`

**Files:**
- Modify: `mcp_servers/weatherflow_calendar/tools.py`
- Test: `mcp_servers/tests/test_calendar_tools.py`

- [ ] Fetch events in window.
- [ ] Convert timed events into busy intervals.
- [ ] Ignore all-day events for minute-level free slots in MVP.
- [ ] Merge overlapping busy intervals.
- [ ] Return slots whose duration is at least `min_duration_minutes`.
- [ ] Test:
  - no events returns one large slot
  - overlapping meetings merge
  - slots shorter than minimum are filtered
  - timezone offsets are preserved
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/tools.py mcp_servers/tests/test_calendar_tools.py
git commit -m "feat: add calendar free slot mcp tool"
```

### Task 8: Implement `calendar.create_event`

**Files:**
- Modify: `mcp_servers/weatherflow_calendar/tools.py`
- Test: `mcp_servers/tests/test_calendar_tools.py`

- [ ] Add write-safety gate:

```python
if not settings.write_tools_enabled and not input.dry_run:
    raise PermissionError("Calendar write tools are disabled.")
```

- [ ] In `dry_run`, return the event payload without calling Google.
- [ ] In non-dry-run, POST to `/calendars/{calendar_id}/events`.
- [ ] Test dry-run and disabled-write behavior.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/tools.py mcp_servers/tests/test_calendar_tools.py
git commit -m "feat: add calendar create event mcp tool"
```

### Task 9: Implement `calendar.create_focus_block`

**Files:**
- Modify: `mcp_servers/weatherflow_calendar/tools.py`
- Test: `mcp_servers/tests/test_calendar_tools.py`

- [ ] Use `find_free_slots` internally.
- [ ] Preferred time windows:
  - `morning`: 09:00-12:00
  - `afternoon`: 13:00-18:00
  - `evening`: 18:00-21:00
- [ ] Pick earliest slot in preferred window; fallback to earliest slot in full day.
- [ ] Create event title exactly as input title.
- [ ] Add description prefix `Created by WeatherFlow`.
- [ ] Test preferred and fallback behavior.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/tools.py mcp_servers/tests/test_calendar_tools.py
git commit -m "feat: add calendar focus block mcp tool"
```

### Task 10: Expose Calendar MCP server

**Files:**
- Create: `mcp_servers/weatherflow_calendar/server.py`
- Test: `mcp_servers/tests/test_calendar_server.py`

- [ ] Use `FastMCP("WeatherFlow Calendar")`.
- [ ] Register four MVP tools.
- [ ] Ensure tool names are exactly:
  - `calendar.search_events`
  - `calendar.find_free_slots`
  - `calendar.create_event`
  - `calendar.create_focus_block`
- [ ] Add a smoke test that imports server and lists registered tools.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_calendar/server.py mcp_servers/tests/test_calendar_server.py
git commit -m "feat: expose calendar mcp server"
```

## Phase 4: Implement GitHub MCP Server MVP

### Task 11: Add GitHub MCP schemas

**Files:**
- Create: `mcp_servers/weatherflow_github/schemas.py`
- Test: `mcp_servers/tests/test_github_schemas.py`

- [ ] Define Pydantic models for:
  - `GitHubRepoInput`
  - `GitHubRecentCommitsInput`
  - `GitHubListIssuesInput`
  - `GitHubCreateIssueInput`
  - `GitHubGetFileInput`
  - `GitHubCreateOrUpdateFileInput`
- [ ] Validate `owner`, `repo`, and `path` are non-empty.
- [ ] Validate `max_bytes <= 100000`.
- [ ] Validate write tools support `dry_run`.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_github/schemas.py mcp_servers/tests/test_github_schemas.py
git commit -m "feat: define github mcp schemas"
```

### Task 12: Implement GitHub HTTP client helper

**Files:**
- Create: `mcp_servers/weatherflow_github/client.py`
- Test: `mcp_servers/tests/test_github_client.py`

- [ ] Read `GITHUB_TOKEN` from env.
- [ ] Build `httpx.AsyncClient` with:
  - `Authorization: Bearer <token>`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
- [ ] Raise clear error when token is missing.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_github/client.py mcp_servers/tests/test_github_client.py
git commit -m "feat: add github mcp client helper"
```

### Task 13: Implement `github.get_repo_status`

**Files:**
- Create: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] Fetch:
  - `/repos/{owner}/{repo}`
  - `/repos/{owner}/{repo}/commits`
  - `/repos/{owner}/{repo}/issues?state=open`
  - `/repos/{owner}/{repo}/pulls?state=open`
- [ ] Exclude PRs from issue count when necessary.
- [ ] Return default branch, latest commit, open issue count, open PR count, and recent activity.
- [ ] Commit:

```bash
git add mcp_servers/weatherflow_github/tools.py mcp_servers/tests/test_github_tools.py
git commit -m "feat: add github repo status mcp tool"
```

### Task 14: Implement `github.get_recent_commits`

**Files:**
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] GET `/repos/{owner}/{repo}/commits` with `sha`, `since`, and `per_page`.
- [ ] Return sha, message, author, committed_at.
- [ ] Test empty commit list and multi-commit response.
- [ ] Commit.

### Task 15: Implement `github.list_issues`

**Files:**
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] GET `/repos/{owner}/{repo}/issues`.
- [ ] Support `state`, comma-joined labels, and `limit`.
- [ ] Filter out PR-shaped issue records that include `pull_request`.
- [ ] Commit.

### Task 16: Implement `github.create_issue`

**Files:**
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] Add write-safety gate with `WF_MCP_WRITE_TOOLS_ENABLED`.
- [ ] Support dry-run response without POST.
- [ ] POST title, body, labels.
- [ ] Test dry-run, disabled write, and successful POST.
- [ ] Commit.

### Task 17: Implement `github.get_file`

**Files:**
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] GET `/repos/{owner}/{repo}/contents/{path}`.
- [ ] Decode base64 content.
- [ ] Enforce `max_bytes`.
- [ ] Return `truncated=true` if content exceeds `max_bytes`.
- [ ] Commit.

### Task 18: Implement `github.create_or_update_file`

**Files:**
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] Add write-safety gate.
- [ ] Support dry-run response with intended path, branch, and message.
- [ ] For update, require `expected_sha`.
- [ ] PUT `/repos/{owner}/{repo}/contents/{path}` with base64 content.
- [ ] Test create, update, missing expected sha, dry-run, disabled write.
- [ ] Commit.

### Task 19: Expose GitHub MCP server

**Files:**
- Create: `mcp_servers/weatherflow_github/server.py`
- Test: `mcp_servers/tests/test_github_server.py`

- [ ] Use `FastMCP("WeatherFlow GitHub")`.
- [ ] Register MVP tools:
  - `github.get_repo_status`
  - `github.get_recent_commits`
  - `github.list_issues`
  - `github.create_issue`
  - `github.get_file`
  - `github.create_or_update_file`
- [ ] Add smoke test for registered tools.
- [ ] Commit.

## Phase 5: Build WF MCP Client

### Task 20: Add MCP client wrapper

**Files:**
- Create: `backend/app/mcp_client/client.py`
- Test: `backend/tests/test_mcp_client.py`

- [ ] Implement `MCPToolClient` with:
  - `connect(command: str)`
  - `list_tools()`
  - `call_tool(name: str, arguments: dict)`
  - timeout handling
  - clean shutdown
- [ ] Use stdio transport first.
- [ ] Map MCP errors to `RuntimeError` with concise messages.
- [ ] Test with fake MCP server process or SDK in-memory harness.
- [ ] Commit.

### Task 21: Add provider mode settings

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_mcp_provider_mode.py`

- [ ] Add:
  - `dev_review_provider_mode`
  - `wf_github_mcp_command`
  - `wf_calendar_mcp_command`
  - `wf_mcp_tool_timeout_seconds`
  - `wf_mcp_write_tools_enabled`
- [ ] Validate accepted modes: `direct`, `mcp`, `dual`.
- [ ] Commit.

## Phase 6: MCP-backed Provider Wrappers

### Task 22: Implement GitHub MCP provider wrapper

**Files:**
- Create: `backend/app/providers/github_mcp.py`
- Test: `backend/tests/test_github_mcp_provider.py`

- [ ] Call `github.get_repo_status` for default Dev Review repository.
- [ ] Call `github.get_recent_commits`.
- [ ] Convert results into existing `ProviderContext` shape:

```python
ProviderContext(
    source="github",
    status="success",
    signals={
        "events": commit_count + activity_count,
        "event_types": {"Commit": commit_count, "Issue": issue_count, "PullRequest": pr_count},
        "repos_touched": 1,
        "repos": [repo_full_name],
    },
    coverage={...},
)
```

- [ ] Tests should assert DevReviewAgent-compatible shape.
- [ ] Commit.

### Task 23: Implement Calendar MCP provider wrapper

**Files:**
- Create: `backend/app/providers/google_calendar_mcp.py`
- Test: `backend/tests/test_calendar_mcp_provider.py`

- [ ] Call `calendar.search_events` for the last `window_days`.
- [ ] Convert returned events into existing `ProviderContext` shape:
  - `meeting_count`
  - `meeting_hours`
  - `after_hours_events`
  - `events`
- [ ] Tests should assert shape equals current direct provider semantics.
- [ ] Commit.

### Task 24: Implement provider registry

**Files:**
- Create: `backend/app/mcp_client/provider_registry.py`
- Modify: `backend/app/routers/dev_review.py`
- Test: `backend/tests/test_mcp_provider_mode.py`

- [ ] For `direct`, return direct providers.
- [ ] For `mcp`, return MCP wrappers.
- [ ] For `dual`, call both and log comparison; return direct result.
- [ ] Preserve current `/api/dev-review/providers` readiness response.
- [ ] Add readiness metadata:
  - `transport: direct | mcp`
  - `mode: direct | mcp | dual`
- [ ] Commit.

## Phase 7: Product Integration for Planning and Action

### Task 25: Add action proposal model

**Files:**
- Modify: `backend/app/memory/schemas.py`
- Create: `backend/tests/test_action_proposals.py`

- [ ] Add `ActionProposal` model:

```python
class ActionProposal(BaseModel):
    id: str
    kind: Literal["calendar_event", "focus_block", "github_issue", "github_file_update"]
    title: str
    rationale: str
    tool_name: str
    tool_arguments: dict[str, Any]
    requires_confirmation: bool = True
```

- [ ] Do not execute write tools automatically from check-in.
- [ ] Commit.

### Task 26: Generate planning actions from check-in

**Files:**
- Modify: `backend/app/agents/planning_agent.py`
- Test: `backend/tests/test_planning_actions.py`

- [ ] Let PlanningAgent propose:
  - focus block when user names a concrete work item and calendar has free slot
  - GitHub issue when user describes a concrete engineering task
- [ ] Store proposals without executing.
- [ ] Commit.

### Task 27: Add confirmed action execution endpoint

**Files:**
- Create: `backend/app/routers/actions.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_actions_api.py`

- [ ] Add `POST /api/actions/{proposal_id}/execute`.
- [ ] Require explicit user confirmation payload:

```json
{
  "confirmed": true
}
```

- [ ] Dispatch to MCP tool through `MCPToolClient`.
- [ ] Reject destructive tools unless `confirmed=true`.
- [ ] Commit.

## Phase 8: Replace Dev Review Direct Path

### Task 28: Enable `dual` mode and compare provider outputs

**Files:**
- Modify: `.env.example`
- Modify: `docs/MCP_PROVIDER_ARCHITECTURE.md`
- Test: existing provider tests

- [ ] Run with:

```bash
DEV_REVIEW_PROVIDER_MODE=dual
```

- [ ] Compare:
  - GitHub event count rough parity
  - repo names
  - Calendar meeting count
  - Calendar meeting hours
- [ ] Log mismatches without failing user requests.
- [ ] Commit.

### Task 29: Switch default to MCP mode

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PHILOSOPHY.md`
- Test: full backend tests

- [ ] Change recommended default:

```bash
DEV_REVIEW_PROVIDER_MODE=mcp
```

- [ ] Keep direct fallback documented.
- [ ] Replace old misleading "MCP connector" wording.
- [ ] Run:

```bash
uv run --package weatherflow-backend --extra dev pytest backend/tests mcp_servers/tests -q
```

- [ ] Commit.

### Task 30: Deprecate direct provider calls

**Files:**
- Modify: `backend/app/providers/github_direct.py`
- Modify: `backend/app/providers/google_calendar_direct.py`
- Modify: `docs/MCP_PROVIDER_ARCHITECTURE.md`

- [ ] Add deprecation comments and logs.
- [ ] Do not delete direct providers until one full release after MCP mode is default.
- [ ] Commit.

## Phase 9: Post-MVP Tool Expansion

### Task 31: Add Calendar update/delete tools

**Files:**
- Modify: `mcp_servers/weatherflow_calendar/schemas.py`
- Modify: `mcp_servers/weatherflow_calendar/tools.py`
- Modify: `mcp_servers/weatherflow_calendar/server.py`
- Test: `mcp_servers/tests/test_calendar_tools.py`

- [ ] Add:
  - `calendar.update_event`
  - `calendar.delete_event`
- [ ] Require write-tools enabled.
- [ ] Require product confirmation before caller executes.
- [ ] Support dry-run.
- [ ] Commit.

### Task 32: Add GitHub list/update tools

**Files:**
- Modify: `mcp_servers/weatherflow_github/schemas.py`
- Modify: `mcp_servers/weatherflow_github/tools.py`
- Modify: `mcp_servers/weatherflow_github/server.py`
- Test: `mcp_servers/tests/test_github_tools.py`

- [ ] Add:
  - `github.list_repos`
  - `github.update_issue`
  - `github.list_pull_requests`
- [ ] Support dry-run where tool mutates state.
- [ ] Commit.

## Verification Checklist

- [ ] `DEV_REVIEW_PROVIDER_MODE=direct` keeps current behavior.
- [ ] `DEV_REVIEW_PROVIDER_MODE=mcp` runs Dev Review through MCP tools.
- [ ] `DEV_REVIEW_PROVIDER_MODE=dual` compares direct and MCP outputs.
- [ ] Calendar read tools do not require write permissions.
- [ ] Calendar write tools are disabled unless `WF_MCP_WRITE_TOOLS_ENABLED=true`.
- [ ] GitHub write tools are disabled unless `WF_MCP_WRITE_TOOLS_ENABLED=true`.
- [ ] No OAuth client secret, Calendar token, or GitHub token is logged.
- [ ] DevReviewAgent still receives `ProviderContext`.
- [ ] Existing dashboard provider readiness remains understandable.
- [ ] README no longer claims direct REST providers are MCP protocol integrations.

## Documentation Updates

Create `docs/MCP_PROVIDER_ARCHITECTURE.md` with:

```text
WF backend
  -> provider registry
  -> direct provider OR MCP provider
  -> MCP client
  -> local MCP server over stdio
  -> GitHub / Google Calendar REST API
```

Include:

- exact tool list
- read/write safety model
- token location and ownership
- how to run servers manually
- how to debug `tools/list`
- how to switch between `direct`, `dual`, and `mcp`

## Rollout Recommendation

1. Land refactors first: move direct providers out of `backend/app/mcp`.
2. Add MCP servers but do not use them from production code yet.
3. Add MCP client and wrappers.
4. Run `dual` mode locally until outputs are close enough.
5. Switch default docs to MCP mode.
6. Keep direct fallback for one release.
7. Delete or archive direct providers only after MCP mode has been stable.

This gives WeatherFlow the MCP protocol boundary without destabilizing the product loop that already works.
