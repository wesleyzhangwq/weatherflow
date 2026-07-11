import re
from dataclasses import dataclass
from typing import Any, Protocol

from weatherflow.capabilities import (
    IdempotencyKind,
    ToolEffect,
    ToolHealth,
    ToolSpec,
)
from weatherflow.runtime import (
    BoundedObservation,
    DefinitiveToolError,
    ToolExecutionContext,
    ToolExecutionResult,
)

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class MCPUnavailableError(ConnectionError):
    pass


class MCPTransport(Protocol):
    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class MCPClient:
    def __init__(self, server_name: str, transport: MCPTransport) -> None:
        if not IDENTIFIER.fullmatch(server_name):
            raise ValueError("invalid MCP server name")
        self.server_name = server_name
        self.transport = transport
        self.server_version = "unknown"

    async def discover(self) -> tuple[ToolSpec, ...]:
        initialized = await self.transport.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "clientInfo": {"name": "weatherflow", "version": "3.0.0"},
                "capabilities": {},
            },
        )
        info = initialized.get("serverInfo", {})
        self.server_version = str(info.get("version", "unknown"))[:100]
        listed = await self.transport.request("tools/list", {})
        raw_tools = listed.get("tools")
        if not isinstance(raw_tools, list):
            raise ValueError("MCP tools/list returned no tool array")
        return tuple(self._normalize_tool(value) for value in raw_tools)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.transport.request(
                "tools/call",
                {"name": name, "arguments": arguments},
            )
        except (ConnectionError, OSError) as error:
            raise MCPUnavailableError(self.server_name) from error

    def _normalize_tool(self, raw: Any) -> ToolSpec:
        if not isinstance(raw, dict):
            raise ValueError("MCP tool must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            raise ValueError("invalid MCP tool name")
        annotations = raw.get("annotations", {})
        if not isinstance(annotations, dict):
            raise ValueError("invalid MCP tool annotations")
        if annotations.get("destructiveHint") is True:
            effect = ToolEffect.DESTRUCTIVE
        elif annotations.get("readOnlyHint") is True:
            effect = ToolEffect.NETWORK_READ
        else:
            effect = ToolEffect.EXTERNAL_WRITE
        return ToolSpec(
            tool_id=f"mcp.{self.server_name}.{name}",
            description=str(raw.get("description") or name)[:1_000],
            input_schema=(
                raw["inputSchema"]
                if isinstance(raw.get("inputSchema"), dict)
                else {"type": "object"}
            ),
            output_schema=(
                raw["outputSchema"]
                if isinstance(raw.get("outputSchema"), dict)
                else {"type": "object"}
            ),
            effect=effect,
            required_scopes=frozenset({f"mcp:{self.server_name}:use"}),
            idempotency=(
                IdempotencyKind.KEY
                if annotations.get("idempotentHint") is True
                else IdempotencyKind.NONE
            ),
            source=f"mcp:{self.server_name}",
            source_version=self.server_version,
        )

    def __repr__(self) -> str:
        return f"MCPClient(server={self.server_name}, transport=<redacted>)"


class MCPExecutor:
    def __init__(self, client: MCPClient) -> None:
        self.client = client
        self.prefix = f"mcp.{client.server_name}."

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if not tool.tool_id.startswith(self.prefix):
            raise LookupError(tool.tool_id)
        if tool.effect in {
            ToolEffect.EXTERNAL_WRITE,
            ToolEffect.DESTRUCTIVE,
            ToolEffect.INSTALL,
            ToolEffect.SENSITIVE,
        } and (context.action_id is None or context.idempotency_key is None):
            raise PermissionError("MCP mutation requires an approved Action context")
        result = await self.client.call(tool.tool_id.removeprefix(self.prefix), arguments)
        if result.get("isError") is True:
            raise DefinitiveToolError("MCP tool returned a definitive error")
        output = {
            "content": result.get("content", []),
            "structured_content": result.get("structuredContent"),
        }
        bounded = BoundedObservation.from_output(output, max_chars=16_000)
        return ToolExecutionResult(output=bounded.output)


@dataclass(frozen=True, slots=True)
class ConnectedMCP:
    client: MCPClient
    tools: tuple[ToolSpec, ...]
    executor: MCPExecutor


class MCPRegistry:
    async def connect(
        self,
        server_name: str,
        transport: MCPTransport,
        *,
        cached_tools: tuple[ToolSpec, ...] = (),
    ) -> ConnectedMCP:
        client = MCPClient(server_name, transport)
        try:
            tools = await client.discover()
        except MCPUnavailableError:
            tools = tuple(
                tool.model_copy(update={"health": ToolHealth.UNAVAILABLE}) for tool in cached_tools
            )
        return ConnectedMCP(
            client=client,
            tools=tools,
            executor=MCPExecutor(client),
        )
