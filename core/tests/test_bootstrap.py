from pathlib import Path

import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import CapabilityCatalog, ToolEffect, ToolSpec
from weatherflow.capabilities.builtin import (
    ResearchSource,
    UnknownCapabilityPackError,
)
from weatherflow.config import Settings
from weatherflow.mcp import MCPInstallAuthorization
from weatherflow.runs import RunStatus, ToolMode
from weatherflow.runtime import (
    FinalTurn,
    LoopStatus,
    ToolCallTurn,
    ToolExecutionResult,
)
from weatherflow.workspaces import Workspace


async def test_runtime_container_rebuilds_from_same_data_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    first = await RuntimeContainer.create(settings)
    workspace = first.default_workspace

    run, outcome = await first.submit_run(
        user_intent="Explain WeatherFlow",
        client_request_id="request-1",
    )

    assert outcome is not None and outcome.status is LoopStatus.WAITING_USER
    assert run.workspace_id == workspace.id
    assert outcome.error == "configure a language model before running this task"

    rebuilt = await RuntimeContainer.create(settings)
    stored_workspace = await rebuilt.workspaces.get(workspace.id)
    stored_run = await rebuilt.runs.get(run.id)
    snapshot = await rebuilt.snapshots.get_by_run_id(run.id)
    checkpoint = await rebuilt.checkpoints.get(run.id)

    assert stored_workspace == workspace
    assert stored_run is not None and stored_run.status is RunStatus.WAITING_USER
    assert stored_run.error_class == "ModelConfigurationRequired"
    assert snapshot is not None
    assert {tool.tool_id for tool in snapshot.tools} == {"developer.read_file"}
    assert checkpoint is not None and checkpoint.state.get("result_committed") is not True
    assert checkpoint.state["rhythm_policy"]["proactivity"] == "silent"
    assert set(rebuilt.workers.definitions) == {
        "release-preparer",
        "release-validator",
        "researcher",
    }


async def test_submit_run_is_idempotent(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))

    first, _ = await container.submit_run(
        user_intent="First intent",
        client_request_id="request-1",
        execute=False,
    )
    repeated, outcome = await container.submit_run(
        user_intent="Ignored retry",
        client_request_id="request-1",
        execute=False,
    )

    assert repeated == first
    assert outcome is None


class OneTurnModel:
    def __init__(self, turn):
        self.turn = turn
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return self.turn


class CountingExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, tool, arguments, context):
        self.calls += 1
        return ToolExecutionResult(output={"status": "shipped"})


class FixedMCPTransport:
    async def request(self, method, params=None):
        if method == "initialize":
            return {"serverInfo": {"name": "filesystem", "version": "1.0.0"}}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read one file",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            }
        if method == "ping":
            return {}
        raise AssertionError(method)

    async def notify(self, method, params=None):
        assert method == "notifications/initialized"

    async def close(self):
        return None


class FixedMCPInstaller:
    async def install(self, preset, *, internal_root: Path, approved_action_id: str):
        executable = preset.executable_path(internal_root)
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("fixture")
        return preset.installation_root(internal_root)

    def is_installed(self, preset, *, internal_root: Path) -> bool:
        return preset.executable_path(internal_root).is_file()


async def test_restart_preserves_pending_turn_and_resumes_after_approval(
    tmp_path: Path,
) -> None:
    tool = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )
    first_model = OneTurnModel(
        ToolCallTurn(call_id="release-v3", tool_id=tool.tool_id, arguments={})
    )
    first = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        model=first_model,
        catalog=CapabilityCatalog([tool]),
    )
    workspace = Workspace.new(
        name="Release",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "release-internal",
        artifact_root=tmp_path / "release-artifacts",
        granted_scopes={"github:write"},
    )
    await first.workspaces.create(workspace)
    run, waiting = await first.submit_run(
        user_intent="Ship release",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )
    assert waiting is not None and waiting.approval_id is not None

    second_model = OneTurnModel(FinalTurn(content="Release shipped"))
    rebuilt = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        model=second_model,
        catalog=CapabilityCatalog([tool]),
    )
    executor = CountingExecutor()
    rebuilt.executors.register(tool.tool_id, executor)
    await rebuilt.approval_coordinator.decide(
        approval_id=waiting.approval_id,
        expected_version=0,
        approved=True,
        decided_by="user",
    )
    outcome = await rebuilt.resume_run(run.id)

    assert outcome.status is LoopStatus.SUCCEEDED
    assert first_model.calls == 1
    assert second_model.calls == 1
    assert executor.calls == 1


class EmptyResearchProvider:
    async def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[ResearchSource, ...]:
        return ()


async def test_installed_packs_define_the_frozen_tool_surface(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        research_provider=EmptyResearchProvider(),
    )
    workspace = Workspace.new(
        name="Research only",
        action_roots=[tmp_path / "research-project"],
        internal_root=tmp_path / "research-internal",
        artifact_root=tmp_path / "research-artifacts",
        granted_scopes={"network:read"},
        installed_packs={"research"},
    )
    await container.workspaces.create(workspace)

    run, _ = await container.submit_run(
        user_intent="Research release requirements",
        workspace_id=workspace.id,
        execute=False,
    )
    snapshot = await container.snapshots.get_by_run_id(run.id)

    assert snapshot is not None
    assert [tool.tool_id for tool in snapshot.tools] == ["research.gather"]
    assert container.executors.get("research.gather") is not None


async def test_enabled_curated_mcp_tools_receive_effective_workspace_scope(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path / "data"))
    project = tmp_path / "project"
    project.mkdir()
    workspace = Workspace.new(
        name="MCP",
        action_roots=[project],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await container.workspaces.create(workspace)
    container.mcp_management.package_installer = FixedMCPInstaller()
    container.mcp_management.transport_factory = lambda argv: FixedMCPTransport()
    await container.mcp_management.install(
        "filesystem",
        workspace=container._mcp_workspace_context(workspace),
        authorization=MCPInstallAuthorization(approved_action_id="approved-install"),
    )
    await container.enable_mcp("filesystem", workspace)

    run, _ = await container.submit_run(
        user_intent="Read a project file with MCP",
        workspace_id=workspace.id,
        execute=False,
    )
    snapshot = await container.snapshots.get_by_run_id(run.id)

    assert snapshot is not None
    assert "mcp.filesystem.read_file" in {tool.tool_id for tool in snapshot.tools}
    assert "mcp:filesystem:use" not in workspace.granted_scopes


async def test_unavailable_pack_provider_is_hidden_fail_closed(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = Workspace.new(
        name="Unavailable research",
        action_roots=[tmp_path / "research-project"],
        internal_root=tmp_path / "research-internal",
        artifact_root=tmp_path / "research-artifacts",
        granted_scopes={"network:read"},
        installed_packs={"research"},
    )
    await container.workspaces.create(workspace)

    run, _ = await container.submit_run(
        user_intent="Research release requirements",
        workspace_id=workspace.id,
        execute=False,
    )
    snapshot = await container.snapshots.get_by_run_id(run.id)

    assert snapshot is not None and snapshot.tools == ()


async def test_unknown_pack_fails_before_run_creation(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = Workspace.new(
        name="Unknown pack",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        installed_packs={"untrusted-pack"},
    )
    await container.workspaces.create(workspace)

    with pytest.raises(UnknownCapabilityPackError, match="untrusted-pack"):
        await container.submit_run(
            user_intent="Use the unknown pack",
            workspace_id=workspace.id,
            execute=False,
        )

    assert await container.runs.list_recent() == []
