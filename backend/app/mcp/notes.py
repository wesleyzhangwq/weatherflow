"""Notes (Obsidian / Markdown) MCP connector — STUB. Reserved for future."""

from __future__ import annotations

from typing import Any

from app.mcp.base import MCPConnector


class NotesConnector(MCPConnector):
    name = "notes"

    async def health(self) -> dict[str, Any]:  # pragma: no cover
        return {"name": self.name, "status": "reserved"}

    async def fetch(self, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError("Notes MCP is reserved for a future iteration")
