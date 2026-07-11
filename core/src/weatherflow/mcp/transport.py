import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from weatherflow.mcp.client import MCPUnavailableError


class StdioMCPTransport:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not argv:
            raise ValueError("MCP command must not be empty")
        self.argv = tuple(argv)
        self._environment = dict(environment or {})
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._lock:
            process = await self._ensure_process()
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
            if process.stdin is None or process.stdout is None:
                raise MCPUnavailableError("stdio unavailable")
            process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
            await process.stdin.drain()
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
            except TimeoutError as error:
                raise MCPUnavailableError("MCP response timed out") from error
            if not line:
                raise MCPUnavailableError("MCP subprocess closed")
            response = json.loads(line)
            if response.get("id") != request_id:
                raise MCPUnavailableError("MCP response id mismatch")
            if "error" in response:
                raise MCPUnavailableError("MCP request failed")
            result = response.get("result")
            if not isinstance(result, dict):
                raise MCPUnavailableError("MCP response result is invalid")
            return result

    async def close(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
        self._process = None

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL"}
        }
        environment.update(self._environment)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
        except OSError as error:
            raise MCPUnavailableError(self.argv[0]) from error
        return self._process

    def __repr__(self) -> str:
        return f"StdioMCPTransport(argv={self.argv!r}, environment=<redacted>)"
