# MCP Provider Architecture

## Overview

```
WF backend
  -> provider registry  (app/mcp_client/provider_registry.py)
  -> direct provider  OR  MCP provider
       |                        |
  github_direct.py         github_mcp.py
  google_calendar_direct.py  google_calendar_mcp.py
                                |
                          MCP client  (app/mcp_client/client.py)
                                |
                     local MCP server over stdio
                                |
                   GitHub / Google Calendar REST API
```

## Tool List

### Calendar MCP MVP

| Tool | Description |
|------|-------------|
| `calendar.search_events` | Search events in a time window with optional keyword filter |
| `calendar.find_free_slots` | Find available time slots respecting busy intervals |
| `calendar.create_event` | Create a calendar event (write-gated) |
| `calendar.create_focus_block` | Auto-find a slot and create a focus block (write-gated) |

### GitHub MCP MVP

| Tool | Description |
|------|-------------|
| `github.get_repo_status` | Get repo default branch, latest commit, open issues and PRs |
| `github.get_recent_commits` | List recent commits on a branch |
| `github.list_issues` | List issues (filters out PRs) |
| `github.create_issue` | Create a GitHub issue (write-gated) |
| `github.get_file` | Read a file, decoded from base64 |
| `github.create_or_update_file` | Write a file to a branch (write-gated) |

## Read/Write Safety Model

- **Read tools** (`search_events`, `find_free_slots`, `get_repo_status`, `get_recent_commits`, `list_issues`, `get_file`) require no write permission.
- **Write tools** (`create_event`, `create_focus_block`, `create_issue`, `create_or_update_file`) require either:
  - `WF_MCP_WRITE_TOOLS_ENABLED=true`, or
  - `dry_run=true` to preview without side effects.
- **Destructive tools** (`calendar.delete_event`, `calendar.update_event`, `github.update_issue`) additionally require product-level `confirmed=true` before the `POST /api/actions/{id}/execute` endpoint will dispatch them.

## Token Location and Ownership

- **GitHub**: `GITHUB_TOKEN` env var — personal access token with `repo` scope.
- **Google Calendar**: `GOOGLE_CALENDAR_TOKEN_FILE` (preferred) or `GOOGLE_CALENDAR_ACCESS_TOKEN`. Run `uv run wf setup-calendar` to create the token file via OAuth.

Neither token is logged. The MCP servers read tokens from env at startup.

## Provider Modes

Set `DEV_REVIEW_PROVIDER_MODE` in `.env`:

| Mode | Behavior |
|------|----------|
| `direct` | Use direct REST connector (default; current behavior) |
| `mcp` | Use MCP tools only |
| `dual` | Call both; log comparison; return direct result (for migration confidence) |

## Running Servers Manually

```bash
# GitHub MCP server
uv run python -m mcp_servers.weatherflow_github.server

# Calendar MCP server
uv run python -m mcp_servers.weatherflow_calendar.server
```

## Debugging `tools/list`

```python
import asyncio
from app.mcp_client.client import MCPToolClient

async def main():
    client = MCPToolClient("uv run python -m mcp_servers.weatherflow_github.server")
    async with client.session() as session:
        tools = await client.list_tools(session)
        for t in tools:
            print(t["name"], "-", t["description"])

asyncio.run(main())
```

## Switching Modes

```bash
# Direct (default)
DEV_REVIEW_PROVIDER_MODE=direct

# MCP only
DEV_REVIEW_PROVIDER_MODE=mcp

# Dual (compare outputs, return direct)
DEV_REVIEW_PROVIDER_MODE=dual
```

After switching to `mcp`, run a few dev reviews via `wf dev-review` and verify the output
matches your expectations before removing the direct provider fallback.
