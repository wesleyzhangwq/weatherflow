from datetime import UTC, datetime
from pathlib import Path

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities.builtin import (
    ProviderUnavailableError,
    ResearchExecutor,
    ResearchSource,
    research_tool_specs,
)
from weatherflow.events import EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime import ToolExecutionContext
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class FakeResearchProvider:
    async def search(self, query: str, *, limit: int) -> tuple[ResearchSource, ...]:
        assert query == "macOS release requirements"
        assert limit == 3
        return (
            ResearchSource(
                title="Notarizing macOS software",
                url="https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution",
                excerpt="Submit the signed app for notarization.",
                retrieved_at=datetime.now(UTC),
            ),
            ResearchSource(
                title="Release checklist",
                url="https://example.test/release",
                excerpt="x" * 10_000,
                retrieved_at=datetime.now(UTC),
            ),
        )


class UnavailableResearchProvider:
    async def search(self, query: str, *, limit: int) -> tuple[ResearchSource, ...]:
        raise ProviderUnavailableError("credential value must not leak")


async def setup(tmp_path: Path, provider):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Research",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"network:read"},
    )
    workspaces = WorkspaceRepository(database)
    await workspaces.create(workspace)
    run = Run.new(
        client_request_id="request-1",
        user_intent="research release requirements",
        workspace_id=workspace.id,
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    artifacts = ArtifactRepository(database)
    store = ArtifactStore(
        database=database,
        repository=artifacts,
        ledger=EventLedger(database),
    )
    executor = ResearchExecutor(
        provider=provider,
        workspaces=workspaces,
        artifacts=store,
    )
    return workspace, run, artifacts, executor


def spec(tool_id: str):
    return next(item for item in research_tool_specs() if item.tool_id == tool_id)


async def test_research_normalizes_sources_and_writes_provenance_artifact(
    tmp_path: Path,
) -> None:
    workspace, run, artifacts, executor = await setup(tmp_path, FakeResearchProvider())

    result = await executor.execute(
        spec("research.gather"),
        {"query": "macOS release requirements", "limit": 3},
        ToolExecutionContext(run_id=run.id, workspace_id=workspace.id),
    )

    assert result.output["status"] == "available"
    assert result.output["sources"][0]["citation"] == "[1] Notarizing macOS software"
    assert len(result.output["sources"][1]["excerpt"]) == 2_000
    assert result.artifact_ids
    manifests = await artifacts.list_run(run.id)
    assert manifests[0].id == result.artifact_ids[0]
    assert manifests[0].validation == {
        "kind": "source-backed-research",
        "source_count": 2,
    }


async def test_research_provider_unavailable_degrades_without_leaking_details(
    tmp_path: Path,
) -> None:
    workspace, run, _, executor = await setup(tmp_path, UnavailableResearchProvider())

    result = await executor.execute(
        spec("research.gather"),
        {"query": "macOS release requirements"},
        ToolExecutionContext(run_id=run.id, workspace_id=workspace.id),
    )

    assert result.output == {
        "status": "unavailable",
        "reason": "research provider unavailable",
        "query": "macOS release requirements",
    }
    assert "credential" not in str(result.output)
    assert result.artifact_ids == ()
