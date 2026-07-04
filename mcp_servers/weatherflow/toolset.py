"""Tool aggregation + MCP ToolAnnotations for the unified server.

Single-definition-point rule: the typed wrapper functions in the two legacy
server modules stay the ONLY place tool signatures are declared (their
signatures are what LLM routers — including Keel's fine-tuned keel-v4 —
were trained against, so they must not drift). This module only *aggregates*
those wrappers and attaches protocol metadata the legacy servers never had:

* ``ToolAnnotations`` — read-only / destructive / idempotent / open-world
  hints, mapped from WeatherFlow's three-state tool taxonomy (ADR D18).
  Annotations are strictly more expressive than the 3-bucket enum: e.g.
  ``github.create_or_update_file`` is "write" in the legacy taxonomy but
  overwrites blobs, so it is honestly marked ``destructiveHint=True``.
* ``_meta.weatherflow.mode`` — the original three-state bucket, so protocol
  clients (our backend's discovery-based registry) can rebuild policy
  without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcp_servers.weatherflow_calendar import server as cal
from mcp_servers.weatherflow_github import server as gh

Mode = Literal["read", "write", "destructive"]

# Annotation presets keyed by mutation profile (all tools hit external APIs,
# hence openWorldHint=True across the board).
_READ = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
_CREATE = dict(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
_UPDATE = dict(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
_DESTROY = dict(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Awaitable[dict]]
    mode: Mode
    hints: dict
    title: str


SPECS: tuple[ToolSpec, ...] = (
    # -- calendar ------------------------------------------------------------
    ToolSpec("calendar.search_events", cal.tool_search_events, "read", _READ,
             "Search calendar events"),
    ToolSpec("calendar.find_free_slots", cal.tool_find_free_slots, "read", _READ,
             "Find free calendar slots"),
    ToolSpec("calendar.create_event", cal.tool_create_event, "write", _CREATE,
             "Create a calendar event"),
    ToolSpec("calendar.create_focus_block", cal.tool_create_focus_block, "write", _CREATE,
             "Create a deep-work focus block"),
    ToolSpec("calendar.update_event", cal.tool_update_event, "write", _UPDATE,
             "Update a calendar event"),
    ToolSpec("calendar.delete_event", cal.tool_delete_event, "destructive", _DESTROY,
             "Delete a calendar event"),
    # -- github --------------------------------------------------------------
    ToolSpec("github.get_repo_status", gh.tool_get_repo_status, "read", _READ,
             "Repo status overview"),
    ToolSpec("github.get_recent_commits", gh.tool_get_recent_commits, "read", _READ,
             "List recent commits"),
    ToolSpec("github.list_issues", gh.tool_list_issues, "read", _READ,
             "List issues"),
    ToolSpec("github.list_pull_requests", gh.tool_list_pull_requests, "read", _READ,
             "List pull requests"),
    ToolSpec("github.list_repos", gh.tool_list_repos, "read", _READ,
             "List accessible repos"),
    ToolSpec("github.get_file", gh.tool_get_file, "read", _READ,
             "Read a file from a repo"),
    ToolSpec("github.create_issue", gh.tool_create_issue, "write", _CREATE,
             "Create an issue"),
    ToolSpec("github.update_issue", gh.tool_update_issue, "write", _UPDATE,
             "Update an issue"),
    # Overwrites existing blobs — more honest than the legacy "write" bucket.
    ToolSpec("github.create_or_update_file", gh.tool_create_or_update_file, "destructive", _DESTROY,
             "Create or overwrite a repo file"),
)


def register_tools(mcp: FastMCP, specs: Iterable[ToolSpec] = SPECS) -> int:
    """Register ``specs`` on ``mcp``; returns the count registered."""
    n = 0
    for spec in specs:
        mcp.add_tool(
            spec.fn,
            name=spec.name,
            title=spec.title,
            annotations=ToolAnnotations(title=spec.title, **spec.hints),
            meta={"weatherflow": {"mode": spec.mode}},
        )
        n += 1
    return n


__all__ = ["Mode", "SPECS", "ToolSpec", "register_tools"]
