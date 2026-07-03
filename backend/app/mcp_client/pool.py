"""Long-lived MCP session pool — one owning task per server command.

Why an actor per connection: the SDK's stdio transport is an anyio context
manager whose cancel scopes must be entered and exited by the *same* task.
Request handlers therefore never touch the transport; each server command
gets one task that owns the subprocess lifecycle (spawn → initialize →
serve queued calls → teardown), and callers await a future.

What this buys over the legacy per-call client (``client.MCPToolClient``):
the ~1s interpreter-spawn + handshake cost is paid once per process
lifetime instead of once per tool call, and a dead transport is restarted
transparently (single retry) on the next call.

Failure policy: a tool-level error is NOT an exception (MCP returns
``isError`` results — surfaced as ``RuntimeError`` after unwrap, connection
kept). Any transport-level exception (including a call timeout, which may
leave the stream desynced) kills the connection; the pool restarts it once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp_client.client import _forwarded_env, _project_root

logger = logging.getLogger(__name__)


@dataclass
class _Request:
    name: str
    arguments: dict
    future: asyncio.Future = field(repr=False)


class _Connection:
    """Actor owning one MCP stdio server subprocess."""

    def __init__(self, command: str, timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        self._queue: asyncio.Queue[_Request | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._boot_error: BaseException | None = None

    # -- lifecycle -----------------------------------------------------------
    def _spawn(self) -> None:
        self._queue = asyncio.Queue()
        self._ready = asyncio.Event()
        self._boot_error = None
        self._task = asyncio.create_task(self._serve(), name=f"mcp-conn:{self.command}")

    async def _serve(self) -> None:
        parts = shlex.split(self.command)
        params = StdioServerParameters(
            command=parts[0], args=parts[1:], env=_forwarded_env(), cwd=_project_root()
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), self.timeout)
                    self._ready.set()
                    await self._loop(session)
        except BaseException as exc:  # noqa: BLE001 — report boot/transport failure to waiters
            self._boot_error = exc
        finally:
            self._ready.set()
            self._drain()

    async def _loop(self, session: ClientSession) -> None:
        while True:
            req = await self._queue.get()
            if req is None:  # shutdown sentinel
                return
            try:
                result = await asyncio.wait_for(
                    session.call_tool(req.name, req.arguments), self.timeout
                )
            except BaseException as exc:  # timeout/transport: fail caller, kill connection
                if not req.future.done():
                    req.future.set_exception(exc)
                raise
            if not req.future.done():
                req.future.set_result(result)

    def _drain(self) -> None:
        while not self._queue.empty():
            req = self._queue.get_nowait()
            if req is not None and not req.future.done():
                req.future.set_exception(
                    RuntimeError(f"MCP connection closed: {self.command}")
                )

    # -- calls ---------------------------------------------------------------
    async def call(self, name: str, arguments: dict) -> Any:
        if self._task is None or self._task.done():
            self._spawn()
        await asyncio.wait_for(self._ready.wait(), self.timeout + 10)
        if self._boot_error is not None or self._task is None or self._task.done():
            raise RuntimeError(
                f"MCP server '{self.command}' is not available: {self._boot_error}"
            )
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Request(name, arguments, fut))
        return await fut

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, 5)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                self._task.cancel()
        self._task = None


class MCPSessionPool:
    """command -> live connection; transparent single restart on failure."""

    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}

    async def call_tool(
        self, name: str, arguments: dict, *, command: str | None = None
    ) -> Any:
        from app.config import get_settings

        s = get_settings()
        cmd = command or s.wf_mcp_unified_command
        conn = self._conns.get(cmd)
        if conn is None:
            conn = self._conns[cmd] = _Connection(cmd, s.wf_mcp_tool_timeout_seconds)
        try:
            raw = await conn.call(name, arguments)
        except Exception:
            logger.warning("MCP call %s failed; restarting '%s' once", name, cmd)
            await conn.aclose()
            self._conns.pop(cmd, None)
            fresh = self._conns.setdefault(
                cmd, _Connection(cmd, s.wf_mcp_tool_timeout_seconds)
            )
            raw = await fresh.call(name, arguments)
        return _unwrap(name, raw)

    async def aclose(self) -> None:
        for conn in self._conns.values():
            await conn.aclose()
        self._conns.clear()


def _unwrap(name: str, result: Any) -> Any:
    """Mirror legacy client semantics: isError -> RuntimeError; prefer
    structuredContent; else parse first text block as JSON; else raw text."""
    if result.isError:
        detail = result.content[0].text if result.content else "unknown error"
        raise RuntimeError(f"MCP tool '{name}' returned an error: {detail}")
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent
    if not result.content:
        return {}
    text = getattr(result.content[0], "text", None)
    if text is None:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# -- module-level singleton ----------------------------------------------------
_POOL: MCPSessionPool | None = None


def get_pool() -> MCPSessionPool:
    global _POOL
    if _POOL is None:
        _POOL = MCPSessionPool()
    return _POOL


async def call_tool(name: str, arguments: dict, *, command: str | None = None) -> Any:
    return await get_pool().call_tool(name, arguments, command=command)


async def shutdown_pool() -> None:
    global _POOL
    if _POOL is not None:
        await _POOL.aclose()
        _POOL = None


__all__ = ["MCPSessionPool", "call_tool", "get_pool", "shutdown_pool"]
