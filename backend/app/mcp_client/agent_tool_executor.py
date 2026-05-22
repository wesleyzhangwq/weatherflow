"""Executor that enforces per-agent budgets when calling MCP tools."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.mcp_client.client import MCPToolClient
from app.mcp_client.tool_registry import MCPToolRegistry
from mcp import ClientSession

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when an agent exceeds a budget constraint."""
    pass


class PermissionDenied(Exception):
    """Raised when an agent lacks permission to call a tool."""
    pass


@dataclass
class AgentBudget:
    """Constraints on an agent's tool calling.

    Attributes:
        max_calls: Maximum number of tool calls allowed.
        max_tokens: Maximum tokens (estimated input + output) allowed.
        max_time_seconds: Maximum wall-clock time allowed.
    """
    max_calls: int = 10
    max_tokens: int = 100_000
    max_time_seconds: float = 300.0


class AgentToolExecutor:
    """Enforces per-agent budgets when calling MCP tools.

    Tracks call count, token usage, and elapsed time. Prevents calls that
    would exceed budgets.
    """

    def __init__(
        self,
        agent_id: str,
        mcp_client: MCPToolClient,
        registry: MCPToolRegistry,
        budget: AgentBudget | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.mcp_client = mcp_client
        self.registry = registry
        self.budget = budget or AgentBudget()

        # Budget tracking
        self.call_count = 0
        self.total_tokens = 0
        self.start_time = time.time()

    async def call_tool(
        self,
        session: ClientSession,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Call a tool, enforcing budget and permission constraints.

        Args:
            session: Active MCP client session.
            tool_name: Name of the tool to call.
            arguments: Tool arguments.

        Returns:
            Tool result.

        Raises:
            PermissionDenied: If agent lacks permission.
            BudgetExceeded: If any budget is exhausted.
        """
        # Check permission
        can_call, reason = self.registry.can_call_tool(self.agent_id, tool_name)
        if not can_call:
            raise PermissionDenied(reason)

        # Check call count budget
        if self.call_count >= self.budget.max_calls:
            raise BudgetExceeded(
                f"Agent '{self.agent_id}' exceeded call budget "
                f"({self.call_count}/{self.budget.max_calls})"
            )

        # Check time budget
        elapsed = time.time() - self.start_time
        if elapsed > self.budget.max_time_seconds:
            raise BudgetExceeded(
                f"Agent '{self.agent_id}' exceeded time budget "
                f"({elapsed:.1f}s/{self.budget.max_time_seconds:.1f}s)"
            )

        # Call tool
        try:
            result = await self.mcp_client.call_tool(session, tool_name, arguments)
        except Exception as exc:
            logger.exception("MCP tool '%s' failed", tool_name)
            raise

        # Update budget tracking
        self.call_count += 1
        self.registry.record_tool_call(tool_name)

        # Estimate token usage (simple heuristic: count JSON chars / 4)
        estimated_tokens = (
            len(str(arguments).encode()) // 4 +
            len(str(result).encode()) // 4
        )
        self.total_tokens += estimated_tokens

        # Check token budget
        if self.total_tokens > self.budget.max_tokens:
            raise BudgetExceeded(
                f"Agent '{self.agent_id}' exceeded token budget "
                f"({self.total_tokens}/{self.budget.max_tokens})"
            )

        return result

    def get_budget_status(self) -> dict[str, Any]:
        """Return current budget usage."""
        elapsed = time.time() - self.start_time
        return {
            "calls": {"used": self.call_count, "limit": self.budget.max_calls},
            "tokens": {"used": self.total_tokens, "limit": self.budget.max_tokens},
            "time_seconds": {"used": elapsed, "limit": self.budget.max_time_seconds},
        }


__all__ = ["AgentBudget", "AgentToolExecutor", "BudgetExceeded", "PermissionDenied"]
