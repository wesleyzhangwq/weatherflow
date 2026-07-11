from dataclasses import dataclass
from uuid import uuid4

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
)
from weatherflow.config import Settings
from weatherflow.events import EventLedger
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    ActionExecutionCoordinator,
    AgentDefinition,
    FinalTurn,
    LoopOutcome,
    LoopStatus,
    ModelAdapter,
    ModelRequest,
    RunCheckpointRepository,
    SharedTurnLoop,
    ToolExecutorRegistry,
)
from weatherflow.storage import Database
from weatherflow.trust import (
    ActionRepository,
    ApprovalCoordinator,
    ApprovalRepository,
    SupervisedPolicy,
)
from weatherflow.workspaces import Workspace, WorkspaceRepository


class EchoModelAdapter:
    async def complete(self, request: ModelRequest):
        content = request.messages[-1].content if request.messages else ""
        return FinalTurn(content=f"Echo: {content}")


@dataclass(slots=True)
class RuntimeContainer:
    settings: Settings
    database: Database
    workspaces: WorkspaceRepository
    default_workspace: Workspace
    ledger: EventLedger
    runs: RunRepository
    run_coordinator: RunCoordinator
    actions: ActionRepository
    approvals: ApprovalRepository
    approval_coordinator: ApprovalCoordinator
    snapshots: CapabilitySnapshotRepository
    capability_coordinator: CapabilitySnapshotCoordinator
    checkpoints: RunCheckpointRepository
    artifacts: ArtifactRepository
    artifact_store: ArtifactStore
    catalog: CapabilityCatalog
    model: ModelAdapter
    executors: ToolExecutorRegistry
    action_execution: ActionExecutionCoordinator
    loop: SharedTurnLoop

    @classmethod
    async def create(
        cls,
        settings: Settings,
        *,
        model: ModelAdapter | None = None,
        catalog: CapabilityCatalog | None = None,
    ) -> "RuntimeContainer":
        database = Database(settings.data_dir / "weatherflow.db")
        await database.initialize()
        workspaces = WorkspaceRepository(database)
        existing_workspaces = await workspaces.list_all()
        if existing_workspaces:
            default_workspace = existing_workspaces[0]
        else:
            default_workspace = Workspace.new(
                name="Default",
                action_roots=[settings.data_dir / "workspace"],
                internal_root=settings.data_dir / "internal",
                artifact_root=settings.data_dir / "artifacts",
                granted_scopes={"workspace:write"},
            )
            await workspaces.create(default_workspace)

        ledger = EventLedger(database)
        runs = RunRepository(database)
        run_coordinator = RunCoordinator(database, runs, ledger)
        actions = ActionRepository(database)
        approvals = ApprovalRepository(database)
        policy = SupervisedPolicy()
        approval_coordinator = ApprovalCoordinator(
            database=database,
            actions=actions,
            approvals=approvals,
            runs=runs,
            run_coordinator=run_coordinator,
            ledger=ledger,
            policy=policy,
        )
        snapshots = CapabilitySnapshotRepository(database)
        capability_coordinator = CapabilitySnapshotCoordinator(
            database=database,
            snapshots=snapshots,
            runs=runs,
            ledger=ledger,
            resolver=CapabilityResolver(policy),
        )
        checkpoints = RunCheckpointRepository(database)
        artifacts = ArtifactRepository(database)
        artifact_store = ArtifactStore(
            database=database,
            repository=artifacts,
            ledger=ledger,
        )
        resolved_catalog = catalog or CapabilityCatalog()
        resolved_model = model or EchoModelAdapter()
        executors = ToolExecutorRegistry()
        action_execution = ActionExecutionCoordinator(
            database=database,
            actions=actions,
            runs=runs,
            run_coordinator=run_coordinator,
            ledger=ledger,
            policy=policy,
        )
        loop = SharedTurnLoop(
            database=database,
            runs=runs,
            run_coordinator=run_coordinator,
            checkpoints=checkpoints,
            snapshots=snapshots,
            ledger=ledger,
            model=resolved_model,
            executors=executors,
            policy=policy,
            approval_coordinator=approval_coordinator,
            action_execution=action_execution,
        )
        return cls(
            settings=settings,
            database=database,
            workspaces=workspaces,
            default_workspace=default_workspace,
            ledger=ledger,
            runs=runs,
            run_coordinator=run_coordinator,
            actions=actions,
            approvals=approvals,
            approval_coordinator=approval_coordinator,
            snapshots=snapshots,
            capability_coordinator=capability_coordinator,
            checkpoints=checkpoints,
            artifacts=artifacts,
            artifact_store=artifact_store,
            catalog=resolved_catalog,
            model=resolved_model,
            executors=executors,
            action_execution=action_execution,
            loop=loop,
        )

    async def submit_run(
        self,
        *,
        user_intent: str,
        client_request_id: str | None = None,
        workspace_id: str | None = None,
        execute: bool = True,
    ) -> tuple[Run, LoopOutcome | None]:
        workspace = (
            await self.workspaces.get(workspace_id)
            if workspace_id is not None
            else self.default_workspace
        )
        if workspace is None:
            raise LookupError(workspace_id)
        run = await self.run_coordinator.create_run(
            client_request_id=client_request_id or str(uuid4()),
            user_intent=user_intent,
            workspace_id=workspace.id,
        )
        if await self.snapshots.get_by_run_id(run.id) is None:
            frozen = await self.capability_coordinator.freeze_for_run(
                run_id=run.id,
                expected_run_version=run.version,
                catalog=self.catalog,
                catalog_revision="runtime-v1",
                workspace=workspace,
                requested_tool_ids={tool.tool_id for tool in self.catalog.all()},
            )
            run = frozen.run
        if not execute:
            return run, None
        current = await self.runs.get(run.id)
        if current is not None and current.status is RunStatus.SUCCEEDED:
            return current, LoopOutcome(
                run_id=current.id,
                status=LoopStatus.SUCCEEDED,
                result_summary=current.result_summary,
            )
        outcome = await self.loop.run(
            run_id=run.id,
            workspace=workspace,
            agent=AgentDefinition(
                agent_id="orchestrator",
                system_prompt="Complete the user's goal with minimum added burden.",
            ),
        )
        return run, outcome
