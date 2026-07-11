import asyncio
from pathlib import Path

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
    ToolEffect,
    ToolSpec,
)
from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    AgentDefinition,
    DelegationTurn,
    FinalTurn,
    RunCheckpointRepository,
    SharedTurnLoop,
    ToolExecutorRegistry,
    WorkerCoordinator,
)
from weatherflow.storage import Database
from weatherflow.trust import SupervisedPolicy
from weatherflow.workspaces import Workspace


class ScriptedModel:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.turns.pop(0)


class BlockingModel:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.calls = 0
        self.three_started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request):
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 3:
            self.three_started.set()
        await self.release.wait()
        self.active -= 1
        return FinalTurn(content=f"Finished {request.messages[0].content}")


def tool(tool_id: str) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description=tool_id,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.OBSERVE,
        source="test",
        source_version="1",
    )


def external_tool() -> ToolSpec:
    return ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.EXTERNAL_WRITE,
        source="test",
        source_version="1",
    )


async def setup_runtime(tmp_path: Path, model, *, max_concurrency: int = 3):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    runs = RunRepository(database)
    run_coordinator = RunCoordinator(database, runs, ledger)
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    parent = await run_coordinator.create_run(
        client_request_id="parent-request",
        user_intent="Prepare the release",
        workspace_id=workspace.id,
    )
    tools = (
        tool("developer.read_file"),
        external_tool(),
        tool("research.gather"),
    )
    snapshots = CapabilitySnapshotRepository(database)
    capability_coordinator = CapabilitySnapshotCoordinator(
        database=database,
        snapshots=snapshots,
        runs=runs,
        ledger=ledger,
        resolver=CapabilityResolver(SupervisedPolicy()),
    )
    frozen = await capability_coordinator.freeze_for_run(
        run_id=parent.id,
        expected_run_version=parent.version,
        catalog=CapabilityCatalog(tools),
        catalog_revision="test-revision",
        workspace=workspace,
        requested_tool_ids={item.tool_id for item in tools},
    )
    artifacts = ArtifactRepository(database)
    checkpoints = RunCheckpointRepository(database)
    workers = WorkerCoordinator(
        database=database,
        runs=runs,
        run_coordinator=run_coordinator,
        snapshots=snapshots,
        capability_coordinator=capability_coordinator,
        ledger=ledger,
        artifacts=artifacts,
        checkpoints=checkpoints,
        definitions={
            "researcher": AgentDefinition(
                agent_id="researcher",
                system_prompt="Find and cite sources.",
                is_leaf=True,
                tool_filter=frozenset({"github.create_release", "research.gather"}),
                max_steps=5,
            )
        },
        max_concurrency=max_concurrency,
    )
    loop = SharedTurnLoop(
        database=database,
        runs=runs,
        run_coordinator=run_coordinator,
        checkpoints=checkpoints,
        snapshots=snapshots,
        ledger=ledger,
        model=model,
        executors=ToolExecutorRegistry(),
        policy=SupervisedPolicy(),
        worker_coordinator=workers,
    )
    workers.bind_loop(loop)
    return (
        database,
        ledger,
        runs,
        frozen.run,
        workspace,
        snapshots,
        artifacts,
        workers,
        loop,
    )


async def test_delegation_uses_shared_loop_and_returns_only_compact_result(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            DelegationTurn(agent_id="researcher", task="Find release requirements"),
            FinalTurn(content="Found notarization requirements"),
            FinalTurn(content="Release preparation complete"),
        ]
    )
    _, ledger, runs, parent, workspace, _, _, _, loop = await setup_runtime(tmp_path, model)

    outcome = await loop.run(
        run_id=parent.id,
        workspace=workspace,
        agent=AgentDefinition(
            agent_id="orchestrator",
            system_prompt="Prepare release",
        ),
    )

    assert outcome.result_summary == "Release preparation complete"
    stored_runs = await runs.list_recent()
    assert len(stored_runs) == 2
    child = next(run for run in stored_runs if run.id != parent.id)
    assert child.status is RunStatus.SUCCEEDED
    assert [tool.tool_id for tool in model.requests[0].tools] == [
        "developer.read_file",
        "github.create_release",
        "research.gather",
    ]
    assert [tool.tool_id for tool in model.requests[1].tools] == ["research.gather"]
    parent_checkpoint = await loop.checkpoints.get(parent.id)
    child_checkpoint = await loop.checkpoints.get(child.id)
    assert parent_checkpoint is not None and child_checkpoint is not None
    assert "Found notarization requirements" in parent_checkpoint.transcript[-2].content
    assert "Find release requirements" not in parent_checkpoint.transcript[-2].content
    assert child_checkpoint.transcript[0].content == "Find release requirements"
    events = await ledger.list_correlation(parent.id)
    assert [event.type for event in events].count("worker.started") == 1
    assert [event.type for event in events].count("worker.completed") == 1


async def test_nested_worker_delegation_fails_child_without_spawning_grandchild(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            DelegationTurn(agent_id="researcher", task="Research"),
            DelegationTurn(agent_id="researcher", task="Nested research"),
            FinalTurn(content="Continued after worker failure"),
        ]
    )
    _, _, runs, parent, workspace, _, _, _, loop = await setup_runtime(tmp_path, model)

    await loop.run(
        run_id=parent.id,
        workspace=workspace,
        agent=AgentDefinition(agent_id="orchestrator", system_prompt="Prepare release"),
    )

    stored_runs = await runs.list_recent()
    assert len(stored_runs) == 2
    child = next(run for run in stored_runs if run.id != parent.id)
    assert child.status is RunStatus.FAILED
    checkpoint = await loop.checkpoints.get(parent.id)
    assert checkpoint is not None
    assert '"status":"failed"' in checkpoint.transcript[-2].content


async def test_worker_limit_is_three_and_completed_delegation_is_reused(
    tmp_path: Path,
) -> None:
    model = BlockingModel()
    (
        database,
        ledger,
        runs,
        parent,
        workspace,
        _,
        artifacts,
        workers,
        _,
    ) = await setup_runtime(tmp_path, model)

    tasks = [
        asyncio.create_task(
            workers.delegate(
                parent_run_id=parent.id,
                delegation_id=f"delegation-{index}",
                workspace=workspace,
                agent_id="researcher",
                task=f"Task {index}",
            )
        )
        for index in range(4)
    ]
    await asyncio.wait_for(model.three_started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert model.peak == 3
    assert model.calls == 3
    model.release.set()
    results = await asyncio.gather(*tasks)

    assert all(result.status == "succeeded" for result in results)
    assert model.calls == 4
    child = next(
        run for run in await runs.list_recent() if run.client_request_id.endswith("delegation-0")
    )
    store = ArtifactStore(
        database=database,
        repository=artifacts,
        ledger=EventLedger(database),
    )
    artifact = await store.put_bytes(
        run_id=child.id,
        workspace=workspace,
        name="worker-note.md",
        media_type="text/markdown",
        data=b"# Worker note\n",
    )

    repeated = await workers.delegate(
        parent_run_id=parent.id,
        delegation_id="delegation-0",
        workspace=workspace,
        agent_id="researcher",
        task="Task 0",
    )

    assert model.calls == 4
    assert repeated.artifact_ids == (artifact.id,)
    events = await ledger.list_correlation(parent.id)
    completed = [
        event
        for event in events
        if event.type == "worker.completed" and event.payload["worker_run_id"] == child.id
    ]
    assert len(completed) == 1
