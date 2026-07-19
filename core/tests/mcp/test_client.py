import json
import sys
from pathlib import Path

import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import ToolEffect, ToolHealth
from weatherflow.capabilities.builtin import activity_tool_specs
from weatherflow.config import Settings
from weatherflow.extensions import PackageInstaller, PackageStore
from weatherflow.mcp import (
    MCPClient,
    MCPRegistry,
    MCPUnavailableError,
    StdioMCPTransport,
)
from weatherflow.runtime import ToolExecutionContext
from weatherflow.workspaces import Workspace


class FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "initialize":
            return {"serverInfo": {"name": "fixture", "version": "1.2.3"}}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "search",
                        "description": "Search sources",
                        "inputSchema": {"type": "object", "required": ["query"]},
                        "annotations": {"readOnlyHint": True},
                    },
                    {
                        "name": "publish",
                        "description": "Publish release",
                        "inputSchema": {"type": "object"},
                        "annotations": {"idempotentHint": True},
                    },
                    {
                        "name": "erase",
                        "description": "Erase remote state",
                        "inputSchema": {"type": "object"},
                        "annotations": {"destructiveHint": True},
                    },
                ]
            }
        if method == "tools/call":
            return {
                "content": [{"type": "text", "text": "source result"}],
                "structuredContent": {"count": 1},
                "isError": False,
            }
        raise AssertionError(method)

    async def close(self):
        return None

    def __repr__(self):
        return "FakeTransport(token=<redacted>)"


class OfflineTransport:
    async def request(self, method, params=None):
        raise MCPUnavailableError("offline")

    async def close(self):
        return None


class NotificationTransport(FakeTransport):
    async def notify(self, method, params=None):
        self.calls.append((method, params))


async def test_discovery_normalizes_annotations_without_granting_scope() -> None:
    registry = MCPRegistry()
    connected = await registry.connect("fixture", FakeTransport())
    tools = {tool.tool_id: tool for tool in connected.tools}

    assert tools["mcp.fixture.search"].effect is ToolEffect.NETWORK_READ
    assert tools["mcp.fixture.publish"].effect is ToolEffect.EXTERNAL_WRITE
    assert tools["mcp.fixture.erase"].effect is ToolEffect.DESTRUCTIVE
    assert all(tool.required_scopes == frozenset({"mcp:fixture:use"}) for tool in tools.values())

    result = await connected.executor.execute(
        tools["mcp.fixture.search"],
        {"query": "WeatherFlow"},
        ToolExecutionContext(run_id="run-1", workspace_id="workspace-1"),
    )
    assert result.output["structured_content"] == {"count": 1}
    assert result.output["content"][0]["text"] == "source result"


async def test_discovery_completes_mcp_initialize_handshake() -> None:
    transport = NotificationTransport()

    await MCPRegistry().connect("fixture", transport)

    assert ("notifications/initialized", {}) in transport.calls


async def test_disconnect_marks_cached_schema_unavailable_and_redacts_transport() -> None:
    available = await MCPRegistry().connect("fixture", FakeTransport())
    degraded = await MCPRegistry().connect(
        "fixture",
        OfflineTransport(),
        cached_tools=available.tools,
    )

    assert all(tool.health is ToolHealth.UNAVAILABLE for tool in degraded.tools)
    assert "token" not in repr(MCPClient("fixture", FakeTransport())).lower()


@pytest.mark.parametrize("name", ["../escape", "bad tool", ""])
async def test_invalid_remote_tool_name_fails_closed(name: str) -> None:
    transport = FakeTransport()

    async def request(method, params=None):
        if method == "initialize":
            return {"serverInfo": {"name": "fixture", "version": "1"}}
        return {"tools": [{"name": name, "description": "bad", "inputSchema": {}}]}

    transport.request = request
    with pytest.raises(ValueError):
        await MCPRegistry().connect("fixture", transport)


async def test_installed_pack_selects_smallest_mcp_surface_for_new_run(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path / "data"),
        mcp_transports={"fixture": FakeTransport()},
    )
    workspace = Workspace.new(
        name="MCP",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"mcp:fixture:use"},
    )
    await container.workspaces.create(workspace)
    source = tmp_path / "mcp-pack"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "kind": "capability_pack",
                "name": "fixture-mcp",
                "version": "1.0.0",
                "description": "Fixture MCP tools",
                "files": [],
                "tool_ids": ["mcp.fixture.search"],
                "requested_scopes": ["mcp:fixture:use"],
            }
        )
    )
    await PackageInstaller(
        database=container.database,
        workspaces=container.workspaces,
        ledger=container.ledger,
        store=PackageStore(workspace.internal_root),
    ).install(
        source,
        workspace_id=workspace.id,
        expected_workspace_version=0,
        installed_by="user",
    )

    run, _ = await container.submit_run(
        user_intent="Search through MCP",
        workspace_id=workspace.id,
        execute=False,
    )
    snapshot = await container.snapshots.get_by_run_id(run.id)

    assert snapshot is not None
    assert {tool.tool_id for tool in snapshot.tools} == {
        "mcp.fixture.search",
        *(tool.tool_id for tool in activity_tool_specs()),
    }
    assert container.executors.get("mcp.fixture.search") is not None


async def test_stdio_transport_reaches_weatherflow_server(tmp_path: Path) -> None:
    transport = StdioMCPTransport(
        [
            sys.executable,
            "-m",
            "weatherflow",
            "--data-dir",
            str(tmp_path),
            "mcp-server",
        ],
        allow_unsandboxed=True,
    )
    try:
        initialized = await transport.request("initialize", {})
        listed = await transport.request("tools/list", {})
    finally:
        await transport.close()

    assert initialized["serverInfo"]["name"] == "weatherflow"
    assert any(tool["name"] == "weatherflow.submit_run" for tool in listed["tools"])


def test_stdio_transport_requires_an_explicit_sandbox_or_test_override() -> None:
    with pytest.raises(ValueError, match="sandbox"):
        StdioMCPTransport([sys.executable, "-V"])
