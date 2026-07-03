"""WF MCP stdio client — wraps the MCP SDK session for tool calls."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 20.0


def _project_root() -> str:
    """Locate the workspace root that contains ``mcp_servers/`` and ``pyproject.toml``.

    Walk up from this file until we find them — works whether uvicorn was
    started from ``./`` or ``./backend``.
    """
    from pathlib import Path

    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "mcp_servers").is_dir() and (parent / "pyproject.toml").is_file():
            return str(parent)
    # Fallback: backend/.. (two parents up from this file's package)
    return str(here.parent.parent.parent.parent)


def _forwarded_env() -> dict[str, str]:
    """Forward MCP-relevant env to the subprocess.

    Two sources:
      1. Settings (which loaded .env via pydantic-settings)
      2. Actual os.environ (so shell exports still work)

    The MCP SDK's stdio_client otherwise strips these.
    """
    from app.config import get_settings

    s = get_settings()
    out: dict[str, str] = {}

    mapping = {
        "GITHUB_TOKEN": s.github_token,
        "GOOGLE_CALENDAR_ACCESS_TOKEN": s.google_calendar_access_token,
        "GOOGLE_CALENDAR_TOKEN_FILE": s.google_calendar_token_file,
        "GOOGLE_CALENDAR_CALENDAR_ID": s.google_calendar_calendar_id,
        "GOOGLE_CALENDAR_BASE_URL": s.google_calendar_base_url,
        "DATA_DIR": s.data_dir,
        "MEMORY_MARKDOWN_DIR": s.memory_markdown_dir,
        # MCP-server-side safety switch — must be 'true' for any write tool
        # to actually call the upstream API.
        "WF_MCP_WRITE_TOOLS_ENABLED": "true" if s.wf_mcp_write_tools_enabled else "false",
    }
    for k, v in mapping.items():
        if v and str(v).strip():
            out[k] = str(v)

    # Also forward shell basics so the subprocess can find uv/python.
    for k in ("PATH", "HOME", "USER", "LANG"):
        v = os.environ.get(k)
        if v:
            out[k] = v
    return out


class MCPToolClient:
    """Lightweight wrapper around an MCP stdio session.

    Usage::

        client = MCPToolClient("uv run python -m mcp_servers.weatherflow_github.server")
        async with client.session() as session:
            tools = await client.list_tools(session)
            result = await client.call_tool(session, "github.get_repo_status", {...})
    """

    def __init__(self, command: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.command = command
        self.timeout = timeout

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[ClientSession, None]:
        parts = shlex.split(self.command)
        params = StdioServerParameters(
            command=parts[0],
            args=parts[1:],
            env=_forwarded_env(),
            cwd=_project_root(),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=self.timeout)
                yield session

    async def list_tools(self, session: ClientSession) -> list[dict[str, Any]]:
        """Full discovery payload — schema, annotations, and server meta.

        The legacy version kept only name/description, which is exactly why a
        hand-maintained registry had to exist; returning the whole surface
        lets the backend build its registry *from the protocol*.
        """
        try:
            result = await asyncio.wait_for(session.list_tools(), timeout=self.timeout)
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema or {},
                    "annotations": t.annotations.model_dump() if t.annotations else None,
                    "meta": t.meta or {},
                }
                for t in result.tools
            ]
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"MCP list_tools timed out after {self.timeout}s") from exc

    async def call_tool(
        self,
        session: ClientSession,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        try:
            result = await asyncio.wait_for(
                session.call_tool(name, arguments),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"MCP tool '{name}' timed out after {self.timeout}s") from exc

        if result.isError:
            content = result.content[0].text if result.content else "unknown error"
            raise RuntimeError(f"MCP tool '{name}' returned an error: {content}")

        if not result.content:
            return {}

        import json
        text = result.content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return text


__all__ = ["MCPToolClient"]
