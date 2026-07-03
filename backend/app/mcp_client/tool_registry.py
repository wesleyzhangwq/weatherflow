"""ToolRegistry — three-mode catalog of Calendar + GitHub tools (ADR D18).

Destructive tools are intentionally NOT registered: there is no path that
exposes them to the LLM, so the agent cannot "discover" them. This is the
v1's enforcement of architecture-v1.md §7.1's destructive-filtering rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from app.memory.schemas import ToolMode

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    mode: ToolMode
    description: str
    parameters: dict  # JSON schema
    server: str  # tool-name prefix, e.g. "calendar" / "github"


def _param(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


# ---------------------------------------------------------------------------
# Calendar tools (§7.2)
# ---------------------------------------------------------------------------
_CALENDAR_TOOLS: list[Tool] = [
    Tool(
        name="calendar.find_free_slots",
        mode="read",
        description="查找指定时间范围内的空档（自动避开已有事件）",
        server="calendar",
        parameters=_param(
            {
                "start_time": {"type": "string", "description": "ISO 8601 起始时刻"},
                "end_time": {"type": "string", "description": "ISO 8601 截止时刻"},
                "min_duration_minutes": {"type": "integer", "default": 45},
            },
            ["start_time", "end_time"],
        ),
    ),
    Tool(
        name="calendar.search_events",
        mode="read",
        description="列出指定时间范围的事件（list_events 的实现）",
        server="calendar",
        parameters=_param(
            {
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "keyword": {"type": "string"},
                "calendar_id": {"type": "string", "default": "primary"},
                "max_results": {"type": "integer", "default": 50},
            },
            ["start_time", "end_time"],
        ),
    ),
    Tool(
        name="calendar.create_focus_block",
        mode="write",
        description="在指定日期创建一个 deep work block，自动找到合适空档",
        server="calendar",
        parameters=_param(
            {
                "title": {"type": "string"},
                "duration_minutes": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "preferred_time": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening"],
                    "default": "morning",
                },
                "priority": {"type": "string", "default": "high"},
            },
            ["title", "duration_minutes", "date"],
        ),
    ),
    Tool(
        name="calendar.create_event",
        mode="write",
        description="创建一般的日历事件",
        server="calendar",
        parameters=_param(
            {
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "description": {"type": "string"},
            },
            ["title", "start_time", "end_time"],
        ),
    ),
    # update_event 与 delete_event 在 v1 不暴露给 agent（前者 write/后者 destructive）
]


# ---------------------------------------------------------------------------
# GitHub tools (§7.3)
# ---------------------------------------------------------------------------
_GITHUB_TOOLS: list[Tool] = [
    Tool(
        name="github.get_repo_status",
        mode="read",
        description="获取指定 repo 的状态概况（最近 commit、open issues/PR）",
        server="github",
        parameters=_param(
            {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "window_days": {"type": "integer", "default": 7},
            },
            ["owner", "repo"],
        ),
    ),
    Tool(
        name="github.get_recent_commits",
        mode="read",
        description="拉取最近的 commit 列表",
        server="github",
        parameters=_param(
            {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
            },
            ["owner", "repo"],
        ),
    ),
    Tool(
        name="github.list_issues",
        mode="read",
        description="列出 issue",
        server="github",
        parameters=_param(
            {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "limit": {"type": "integer", "default": 30},
            },
            ["owner", "repo"],
        ),
    ),
    Tool(
        name="github.list_pull_requests",
        mode="read",
        description="列出 PR",
        server="github",
        parameters=_param(
            {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "limit": {"type": "integer", "default": 30},
            },
            ["owner", "repo"],
        ),
    ),
    Tool(
        name="github.list_repos",
        mode="read",
        description="列出你可访问的 repo",
        server="github",
        parameters=_param(
            {"limit": {"type": "integer", "default": 30}},
            [],
        ),
    ),
    Tool(
        name="github.create_issue",
        mode="write",
        description="创建一个 issue",
        server="github",
        parameters=_param(
            {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "string", "description": "逗号分隔"},
            },
            ["owner", "repo", "title"],
        ),
    ),
    # update_issue (write) 不暴露 — v1 保守
    # close/delete_* (destructive) 完全不注册
]


@dataclass
class ToolRegistry:
    tools: Dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.mode == "destructive":
            # never register, see module docstring
            return
        self.tools[tool.name] = tool

    def list_tools(self, *, mode: ToolMode | None = None) -> List[Tool]:
        if mode is None:
            return list(self.tools.values())
        return [t for t in self.tools.values() if t.mode == mode]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def openai_tool_schemas(self) -> List[dict]:
        """Render as OpenAI/function-calling tool schemas."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.tools.values()
        ]


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for t in (*_CALENDAR_TOOLS, *_GITHUB_TOOLS):
        reg.register(t)
    return reg


# ---------------------------------------------------------------------------
# Protocol-first discovery (overhaul phase 2)
#
# The MCP server is the single source of truth for tool schemas. At startup
# the backend lists tools over the protocol and rebuilds its registry from
# what the server actually serves: three-state mode comes from the server's
# `_meta.weatherflow.mode` (authoritative) or, for foreign servers, from
# ToolAnnotations. The hand-written tables above remain only as an offline
# fallback (tests / server unavailable) — they are no longer the truth.
# ---------------------------------------------------------------------------

def _mode_from_annotations(annotations: dict | None) -> ToolMode:
    if annotations is None:
        return "write"  # unknown mutation profile -> most conservative gated bucket
    if annotations.get("readOnlyHint"):
        return "read"
    if annotations.get("destructiveHint"):
        return "destructive"
    return "write"


async def discover_from_mcp(
    command: str | None = None, timeout: float = 20.0
) -> ToolRegistry | None:
    """Build a registry from the unified MCP server; None on any failure."""
    from app.config import get_settings
    from app.mcp_client.client import MCPToolClient

    cmd = command or get_settings().wf_mcp_unified_command
    client = MCPToolClient(cmd, timeout=timeout)
    try:
        async with client.session() as session:
            listed = await client.list_tools(session)
    except Exception as exc:  # noqa: BLE001 — discovery must never break startup
        logger.warning("MCP tool discovery failed (%s); using static registry", exc)
        return None

    reg = ToolRegistry()
    skipped: list[str] = []
    for t in listed:
        mode = (t.get("meta") or {}).get("weatherflow", {}).get("mode") or (
            _mode_from_annotations(t.get("annotations"))
        )
        if mode == "destructive":
            skipped.append(t["name"])  # invariant: never reaches the LLM
        reg.register(
            Tool(
                name=t["name"],
                mode=mode,
                description=t["description"],
                parameters=t.get("input_schema") or {},
                server=t["name"].split(".", 1)[0],
            )
        )
    if not reg.tools:
        logger.warning("MCP discovery returned no registrable tools; using static registry")
        return None
    logger.info(
        "Tool registry discovered via MCP: %d tools (%d destructive filtered: %s)",
        len(reg.tools), len(skipped), ", ".join(skipped) or "-",
    )
    return reg


def set_registry(reg: ToolRegistry) -> None:
    global _REGISTRY
    _REGISTRY = reg


async def init_registry_via_discovery() -> bool:
    """Swap the process registry for a protocol-discovered one. True on success."""
    reg = await discover_from_mcp()
    if reg is None:
        return False
    set_registry(reg)
    return True


# Singleton — v1 only ever has one user, one registry.
_REGISTRY: ToolRegistry | None = None


def registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "discover_from_mcp",
    "init_registry_via_discovery",
    "registry",
    "set_registry",
]
