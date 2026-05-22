"""Central registry of MCP tools with permissions and rate limiting."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    """Metadata for a single MCP tool."""
    name: str
    description: str
    provider: str  # e.g., "github", "google_calendar"


@dataclass
class ToolPermission:
    """Access control policy for a tool."""
    tool_name: str
    allowed_agents: set[str] = field(default_factory=set)
    max_calls_per_hour: int | None = None


class MCPToolRegistry:
    """Central catalog of available tools with permissions and rate limits.

    Tracks what tools exist, who can call them, and rate limits.
    Tool metadata is populated from MCP providers at startup.
    """

    def __init__(self) -> None:
        self.tools: dict[str, ToolInfo] = {}
        self.permissions: dict[str, ToolPermission] = {}
        self.call_history: dict[str, list[float]] = {}  # tool_name -> timestamps

    def register_tool(self, info: ToolInfo) -> None:
        """Register a tool discovered from an MCP provider."""
        self.tools[info.name] = info
        if info.name not in self.permissions:
            self.permissions[info.name] = ToolPermission(tool_name=info.name)
        if info.name not in self.call_history:
            self.call_history[info.name] = []

    def register_permission(self, permission: ToolPermission) -> None:
        """Register access control for a tool."""
        self.permissions[permission.tool_name] = permission

    def grant_permission(
        self,
        agent_id: str,
        tool_name: str,
        max_calls_per_hour: int | None = None,
    ) -> None:
        """Grant an agent permission to call a tool."""
        if tool_name not in self.permissions:
            self.permissions[tool_name] = ToolPermission(tool_name=tool_name)
        perm = self.permissions[tool_name]
        perm.allowed_agents.add(agent_id)
        if max_calls_per_hour is not None:
            perm.max_calls_per_hour = max_calls_per_hour

    def get_available_tools(self, agent_id: str) -> list[ToolInfo]:
        """List tools available to this agent.

        Only tools where the agent has explicit permission are available.
        """
        available = []
        for tool_name, tool_info in self.tools.items():
            can_call, _ = self.can_call_tool(agent_id, tool_name)
            if can_call:
                available.append(tool_info)
        return available

    def can_call_tool(self, agent_id: str, tool_name: str) -> tuple[bool, str]:
        """Check if agent can call this tool now.

        Returns: (can_call, reason) where reason is empty if can_call is True.

        Permission model: agents must be explicitly granted permission. If a tool
        has no agents in its allowed_agents set, no one can call it.
        """
        if tool_name not in self.tools:
            return False, f"Tool '{tool_name}' not registered"

        perm = self.permissions.get(tool_name)
        # If no permission record or allowed_agents is empty, deny access
        if not perm or not perm.allowed_agents:
            return False, f"Agent '{agent_id}' not permitted to call '{tool_name}'"

        # Agent must be in the allowed_agents set
        if agent_id not in perm.allowed_agents:
            return False, f"Agent '{agent_id}' not permitted to call '{tool_name}'"

        # Check rate limit
        if perm.max_calls_per_hour:
            now = time.time()
            hour_ago = now - 3600
            recent_calls = [t for t in self.call_history[tool_name] if t > hour_ago]
            if len(recent_calls) >= perm.max_calls_per_hour:
                return False, f"Rate limit exceeded for '{tool_name}' ({perm.max_calls_per_hour} calls/hour)"

        return True, ""

    def record_tool_call(self, tool_name: str) -> None:
        """Record that a tool was called (for rate limiting)."""
        if tool_name in self.call_history:
            self.call_history[tool_name].append(time.time())


__all__ = ["ToolInfo", "ToolPermission", "MCPToolRegistry"]
