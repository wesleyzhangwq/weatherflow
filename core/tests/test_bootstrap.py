from datetime import UTC, datetime
from pathlib import Path

import pytest

from weatherflow.activity import (
    ActivityAnalysisRouteMismatchError,
    ActivitySourceHealth,
    ActivityWatchDiscovery,
    ActivityWatchInfo,
    ActivityWatchUnavailable,
    ActivityWindowPlanner,
    CategoryRuleVersion,
    SummaryTaskType,
)
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import CapabilityCatalog, ToolEffect, ToolSpec
from weatherflow.capabilities.builtin import (
    ResearchSource,
    UnknownCapabilityPackError,
    activity_tool_specs,
)
from weatherflow.config import Settings
from weatherflow.extensions import CredentialRef
from weatherflow.mcp import MCPInstallAuthorization
from weatherflow.models import ModelConfiguration, ModelProvider
from weatherflow.runs import RunStatus, ToolMode
from weatherflow.runtime import (
    FinalTurn,
    LoopStatus,
    ToolCallTurn,
    ToolExecutionResult,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


def test_orchestrator_prompt_includes_frozen_asia_shanghai_time_anchor() -> None:
    prompt = RuntimeContainer._orchestrator_prompt(
        {},
        {},
        [],
        [],
        time_anchor=datetime(2026, 7, 17, 10, 42, 17, tzinfo=UTC),
    )

    assert "time_anchor_utc=2026-07-17T10:42:17+00:00" in prompt
    assert "time_anchor_asia_shanghai=2026-07-17T18:42:17+08:00" in prompt
    assert "past 24 hours" in prompt


@pytest.mark.parametrize("mismatch", ["provider", "version"])
async def test_activity_summary_route_rejects_stale_provider_or_configuration_version(
    tmp_path: Path,
    mismatch: str,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    current = await container.activity_repository.summary_settings()
    assert current is not None
    updated_at = datetime(2026, 7, 18, 1, tzinfo=UTC)
    configuration = ModelConfiguration(
        workspace_id=current.model_workspace_id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        updated_at=updated_at,
    )
    async with container.database.transaction() as connection:
        configuration = await container.model_configurations.repository.save_in(
            connection,
            configuration,
        )
    selection = {
        "provider": configuration.provider.value,
        "model": configuration.model,
        "model_configuration_version": configuration.version,
        "updated_at": updated_at,
    }
    if mismatch == "provider":
        selection["provider"] = "deepseek"
    else:
        selection["model_configuration_version"] = configuration.version + 1
    await container.activity_repository.save_summary_settings(
        current.model_copy(update=selection),
        expected_version=current.version,
        now=updated_at,
    )
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=datetime(2026, 7, 17, 16, tzinfo=UTC),
        window_end=datetime(2026, 7, 17, 22, tzinfo=UTC),
        created_at=updated_at,
    )
    resolver = container.activity_recovery.summaries.analyzer.resolve_route
    assert resolver is not None

    with pytest.raises(ActivityAnalysisRouteMismatchError):
        await resolver(task)


async def test_activity_summary_route_supports_an_independent_model_on_current_provider(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    current = await container.activity_repository.summary_settings()
    assert current is not None
    updated_at = datetime(2026, 7, 18, 1, tzinfo=UTC)
    configuration = ModelConfiguration(
        workspace_id=current.model_workspace_id,
        provider=ModelProvider.MINIMAX,
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
        credential_ref=CredentialRef(provider="minimax", name="api_key"),
        updated_at=updated_at,
    )
    async with container.database.transaction() as connection:
        configuration = await container.model_configurations.repository.save_in(
            connection,
            configuration,
        )
    await container.activity_repository.save_summary_settings(
        current.model_copy(
            update={
                "provider": configuration.provider.value,
                "model": "MiniMax-M2.7-highspeed",
                "model_configuration_version": configuration.version,
                "updated_at": updated_at,
            }
        ),
        expected_version=current.version,
        now=updated_at,
    )
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=datetime(2026, 7, 17, 16, tzinfo=UTC),
        window_end=datetime(2026, 7, 17, 22, tzinfo=UTC),
        created_at=updated_at,
    )
    resolver = container.activity_recovery.summaries.analyzer.resolve_route
    assert resolver is not None

    route = await resolver(task)

    assert route is not None
    assert route.provider == "minimax"
    assert route.model == "MiniMax-M2.7-highspeed"
    assert route.configuration_version == configuration.version
    assert route.adapter is not None
    assert route.adapter.model == "MiniMax-M2.7-highspeed"


async def test_production_catalog_omits_unwired_legacy_providers_and_wires_calendar(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))

    tool_ids = {tool.tool_id for tool in container.catalog.all()}

    assert not {
        "github.inspect_release",
        "github.create_release",
        "research.gather",
    }.intersection(tool_ids)
    assert {
        "calendar.list_events",
        "calendar.create_event",
        "personal.plan_day",
        "personal.prepare_meeting",
        "personal.propose_schedule",
        "extensions.install",
    }.issubset(tool_ids)
    assert all(
        container.executors.get(tool_id) is not None
        for tool_id in {
            "calendar.list_events",
            "calendar.create_event",
            "personal.plan_day",
            "personal.prepare_meeting",
            "personal.propose_schedule",
            "extensions.install",
        }
    )


async def test_startup_reconciles_personal_pack_once_for_existing_workspaces(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    database = Database(settings.data_dir / "weatherflow.db")
    await database.initialize()
    repository = WorkspaceRepository(database)
    legacy = Workspace.new(
        name="Legacy",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:read", "workspace:write", "workspace:execute"},
        installed_packs={"developer"},
    )
    await repository.create(legacy)

    first = await RuntimeContainer.create(settings)
    updated = await first.workspaces.get(legacy.id)
    first_events = await first.ledger.list_stream("workspace", legacy.id, limit=100)

    assert updated is not None
    assert updated.installed_packs == ("developer", "personal_operations")
    assert updated.version == 1
    assert [event.type for event in first_events].count("workspace.builtin_packs_reconciled") == 1

    rebuilt = await RuntimeContainer.create(settings)
    stable = await rebuilt.workspaces.get(legacy.id)
    rebuilt_events = await rebuilt.ledger.list_stream("workspace", legacy.id, limit=100)

    assert stable is not None and stable.version == 1
    assert [event.type for event in rebuilt_events].count("workspace.builtin_packs_reconciled") == 1


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
    assert {tool.tool_id for tool in snapshot.tools} == {
        "developer.read_file",
        *(tool.tool_id for tool in activity_tool_specs()),
    }
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
                        "name": "read_text_file",
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


class StubActivityWatchClient:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.discover_calls = 0
        self.closed = False

    async def discover(self) -> ActivityWatchDiscovery:
        self.discover_calls += 1
        if not self.available:
            raise ActivityWatchUnavailable("offline")
        return ActivityWatchDiscovery(
            info=ActivityWatchInfo(
                hostname="macbook",
                version="0.13.2",
                device_id="device-1",
            ),
            buckets=(),
            data_start=None,
            data_end=None,
            settings={},
            category_rules=CategoryRuleVersion(
                id="a" * 64,
                canonical_json="[]",
                rule_count=0,
            ),
        )

    async def buckets(self):
        if not self.available:
            raise ActivityWatchUnavailable("offline")
        return []

    async def events(self, *_args, **_kwargs):
        if not self.available:
            raise ActivityWatchUnavailable("offline")
        return []

    async def info(self):
        return (await self.discover()).info

    async def settings(self):
        return {}

    async def classes(self):
        return []

    async def query(self, **_kwargs):
        if not self.available:
            raise ActivityWatchUnavailable("offline")
        return [[]]

    async def close(self) -> None:
        self.closed = True


async def test_activitywatch_startup_probe_tools_scheduler_and_close_are_owned(
    tmp_path: Path,
) -> None:
    activity_client = StubActivityWatchClient()
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        activity_client=activity_client,
    )

    source = await container.activity.source_status()
    assert activity_client.discover_calls >= 1
    assert source.health is ActivitySourceHealth.AVAILABLE
    assert {
        tool.tool_id
        for tool in activity_tool_specs()
        if container.executors.get(tool.tool_id) is not None
    } == {tool.tool_id for tool in activity_tool_specs()}

    await container.start_background(
        include_connector_sync=False,
        include_automation_scheduler=False,
        include_activity_scheduler=True,
    )
    assert container.activity_scheduler.running is True

    await container.close()

    assert container.activity_scheduler.running is False
    assert activity_client.closed is True


async def test_activitywatch_offline_does_not_block_runtime_start(
    tmp_path: Path,
) -> None:
    activity_client = StubActivityWatchClient(available=False)

    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        activity_client=activity_client,
    )

    source = await container.activity.source_status()
    assert source.health is ActivitySourceHealth.DEGRADED
    assert source.error_code == "activitywatch_unavailable"
    await container.close()


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
    assert {tool.tool_id for tool in snapshot.tools} == {
        "research.gather",
        *(tool.tool_id for tool in activity_tool_specs()),
    }
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
    assert "mcp.filesystem.read_text_file" in {tool.tool_id for tool in snapshot.tools}
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

    assert snapshot is not None
    assert {tool.tool_id for tool in snapshot.tools} == {
        tool.tool_id for tool in activity_tool_specs()
    }


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
