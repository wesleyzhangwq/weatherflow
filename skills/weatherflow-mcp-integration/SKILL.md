---
name: weatherflow-mcp-integration
description: Mount, configure, and debug the WeatherFlow MCP server in any MCP host (Claude Code, Keel, custom clients) — transports, env contract, safety gates, and the classic failure modes. Use when connecting WeatherFlow to an agent host, when tools error or hang, or when deciding between the unified and per-domain servers.
---

# WeatherFlow MCP Integration

## Mounting

**Claude Code**
```bash
claude mcp add weatherflow -- uv run python -m mcp_servers.weatherflow
```

**Generic host config (stdio)**
```json
{"mcpServers": {"weatherflow": {
  "command": "uv", "args": ["run", "python", "-m", "mcp_servers.weatherflow"],
  "cwd": "/path/to/WeatherFlow"
}}}
```

**Remote / multi-client** — streamable HTTP on :8765:
```bash
uv run python -m mcp_servers.weatherflow --transport http --port 8765
```

Narrow surfaces (calendar-only / github-only hosts): the legacy entry points
`mcp_servers.weatherflow_calendar.server` / `weatherflow_github.server`
serve identical schemas (drift-guarded by tests).

## Env contract

| Var | Needed for | Notes |
|---|---|---|
| `GITHUB_TOKEN` | all `github.*` tools | classic PAT, repo read scope + issues write if proposing |
| `GOOGLE_CALENDAR_ACCESS_TOKEN` or `GOOGLE_CALENDAR_TOKEN_FILE` | all `calendar.*` tools | access tokens expire hourly — prefer the token file |
| `WF_MCP_WRITE_TOOLS_ENABLED` | any non-read tool executing for real | defence-in-depth; unset/false → writes require `dry_run=true` |
| `DATA_DIR`, `MEMORY_MARKDOWN_DIR` | `weatherflow://` resources | resources degrade to `{"available": false}` when absent |

## Safety model (what a host should enforce)

1. Read `ToolAnnotations`: `readOnlyHint=true` → safe to auto-run.
2. Non-read → surface to the user as a confirmable action; all write tools
   accept `dry_run=true` for effect preview.
3. `destructiveHint=true` (`calendar.delete_event`,
   `github.create_or_update_file`) → hardest gate or don't expose to the
   model at all. WeatherFlow's own backend filters these out of the LLM
   surface entirely; `_meta.weatherflow.mode` carries the three-state bucket
   if you want the same policy.

## Failure modes (in observed frequency order)

1. **Tool "works in shell, fails in host"** → the host didn't forward env.
   MCP subprocesses do NOT inherit your shell `.env`; put vars in the host's
   server config `env` block.
2. **First call slow (~1s)** → uv/python spawn + handshake. Keep the session
   alive (WeatherFlow's backend uses an actor-owned session pool; copy that
   pattern) instead of reconnecting per call.
3. **Calendar 401** → access token expired (hourly); refresh or switch to
   `GOOGLE_CALENDAR_TOKEN_FILE`.
4. **Resources return available:false** → server can't see the L1/profile
   stores; set `DATA_DIR`/`MEMORY_MARKDOWN_DIR` to the backend's data paths.
5. **Hang on init** → the command isn't reaching the venv (use absolute
   `cwd` or the repo's `.venv/bin/python`).

## Reference consumer

Keel's agent runtime mounts this server as a plain MCP client
(`keel_agent/executors/weatherflow.py`) — spawn, initialize, call_tool,
with `dry_run=true` forced on writes. Reading it is the fastest way to see
the full contract in ~100 lines.
