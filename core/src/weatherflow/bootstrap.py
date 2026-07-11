from dataclasses import dataclass
from uuid import uuid4

from weatherflow.artifacts import ArtifactManifest, ArtifactRepository, ArtifactStore
from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilityResolver,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
)
from weatherflow.capabilities.builtin import (
    DEVELOPER_PACK,
    CalendarExecutor,
    CalendarProvider,
    DeveloperExecutor,
    GitHubExecutor,
    GitHubProvider,
    ResearchExecutor,
    ResearchProvider,
    builtin_tool_specs,
    calendar_tool_specs,
    developer_tool_specs,
    github_tool_specs,
    research_tool_specs,
    tool_ids_for_installed_packs,
)
from weatherflow.config import Settings
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.rhythm import RhythmEstimator, RhythmService, RhythmSnapshotRepository
from weatherflow.runs import Run, RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime import (
    ActionExecutionCoordinator,
    AgentDefinition,
    AgentMessage,
    FinalTurn,
    LoopOutcome,
    LoopStatus,
    MessageRole,
    ModelAdapter,
    ModelRequest,
    RunCheckpoint,
    RunCheckpointRepository,
    SharedTurnLoop,
    ToolExecutorRegistry,
    WorkerCoordinator,
    builtin_worker_definitions,
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
    rhythm_snapshots: RhythmSnapshotRepository
    rhythm: RhythmService
    catalog: CapabilityCatalog
    model: ModelAdapter
    executors: ToolExecutorRegistry
    action_execution: ActionExecutionCoordinator
    loop: SharedTurnLoop
    workers: WorkerCoordinator
    use_builtin_pack_resolution: bool

    @classmethod
    async def create(
        cls,
        settings: Settings,
        *,
        model: ModelAdapter | None = None,
        catalog: CapabilityCatalog | None = None,
        research_provider: ResearchProvider | None = None,
        calendar_provider: CalendarProvider | None = None,
        github_provider: GitHubProvider | None = None,
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
                granted_scopes={
                    "workspace:read",
                    "workspace:write",
                    "workspace:execute",
                },
                installed_packs={DEVELOPER_PACK},
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
        rhythm_snapshots = RhythmSnapshotRepository(database)
        rhythm = RhythmService(
            database=database,
            ledger=ledger,
            snapshots=rhythm_snapshots,
            estimator=RhythmEstimator(),
        )
        use_builtin_pack_resolution = catalog is None
        resolved_catalog = catalog or CapabilityCatalog(
            builtin_tool_specs(
                research_available=research_provider is not None,
                calendar_available=calendar_provider is not None,
                github_available=github_provider is not None,
            )
        )
        resolved_model = model or EchoModelAdapter()
        executors = ToolExecutorRegistry()
        if use_builtin_pack_resolution:
            developer_executor = DeveloperExecutor(workspaces, artifacts=artifact_store)
            for tool in developer_tool_specs():
                executors.register(tool.tool_id, developer_executor)
            if research_provider is not None:
                research_executor = ResearchExecutor(
                    provider=research_provider,
                    workspaces=workspaces,
                    artifacts=artifact_store,
                )
                for tool in research_tool_specs():
                    executors.register(tool.tool_id, research_executor)
            if calendar_provider is not None:
                calendar_executor = CalendarExecutor(calendar_provider)
                for tool in calendar_tool_specs():
                    executors.register(tool.tool_id, calendar_executor)
            if github_provider is not None:
                github_executor = GitHubExecutor(github_provider)
                for tool in github_tool_specs():
                    executors.register(tool.tool_id, github_executor)
        action_execution = ActionExecutionCoordinator(
            database=database,
            actions=actions,
            runs=runs,
            run_coordinator=run_coordinator,
            ledger=ledger,
            policy=policy,
        )
        workers = WorkerCoordinator(
            database=database,
            runs=runs,
            run_coordinator=run_coordinator,
            snapshots=snapshots,
            capability_coordinator=capability_coordinator,
            ledger=ledger,
            artifacts=artifacts,
            definitions=builtin_worker_definitions(),
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
            worker_coordinator=workers,
        )
        workers.bind_loop(loop)
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
            rhythm_snapshots=rhythm_snapshots,
            rhythm=rhythm,
            catalog=resolved_catalog,
            model=resolved_model,
            executors=executors,
            action_execution=action_execution,
            loop=loop,
            workers=workers,
            use_builtin_pack_resolution=use_builtin_pack_resolution,
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
        requested_tool_ids = (
            tool_ids_for_installed_packs(workspace.installed_packs)
            if self.use_builtin_pack_resolution
            else {tool.tool_id for tool in self.catalog.all()}
        )
        run = await self.run_coordinator.create_run(
            client_request_id=client_request_id or str(uuid4()),
            user_intent=user_intent,
            workspace_id=workspace.id,
        )
        if run.rhythm_snapshot_id is None:
            run = await self._bind_rhythm_context(run, workspace)
        if await self.snapshots.get_by_run_id(run.id) is None:
            frozen = await self.capability_coordinator.freeze_for_run(
                run_id=run.id,
                expected_run_version=run.version,
                catalog=self.catalog,
                catalog_revision="weatherflow-v3-p3a",
                workspace=workspace,
                requested_tool_ids=requested_tool_ids,
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
        outcome = await self.resume_run(run.id)
        return run, outcome

    async def resume_run(self, run_id: str) -> LoopOutcome:
        run = await self.runs.get(run_id)
        if run is None:
            raise LookupError(run_id)
        workspace = await self.workspaces.get(run.workspace_id)
        if workspace is None:
            raise LookupError(run.workspace_id)
        checkpoint = await self.checkpoints.get(run.id)
        policy = checkpoint.state.get("rhythm_policy", {}) if checkpoint else {}
        outcome = await self.loop.run(
            run_id=run.id,
            workspace=workspace,
            agent=AgentDefinition(
                agent_id="orchestrator",
                system_prompt=self._orchestrator_prompt(policy),
            ),
        )
        if outcome.status in {
            LoopStatus.SUCCEEDED,
            LoopStatus.FAILED,
            LoopStatus.NEEDS_REVIEW,
        }:
            terminal = await self.runs.get(run.id)
            final_checkpoint = await self.checkpoints.get(run.id)
            if terminal is None or final_checkpoint is None:
                raise RuntimeError(run.id)
            await self.rhythm.record_task_behavior(
                workspace_id=workspace.id,
                run_id=run.id,
                outcome=terminal.status.value,
                observed_at=terminal.updated_at,
                duration_seconds=max(
                    0.0, (terminal.updated_at - terminal.created_at).total_seconds()
                ),
                step_count=final_checkpoint.step_index,
            )
        return outcome

    async def run_artifacts(self, run_id: str) -> list[ArtifactManifest]:
        run = await self.runs.get(run_id)
        if run is None:
            raise LookupError(run_id)
        timeline = await self.ledger.list_correlation(run_id, limit=1000)
        worker_run_ids = tuple(
            dict.fromkeys(
                str(event.payload["worker_run_id"])
                for event in timeline
                if event.type == "worker.completed"
            )
        )
        return [
            artifact
            for related_run_id in (run_id, *worker_run_ids)
            for artifact in await self.artifacts.list_run(related_run_id)
        ]

    async def _bind_rhythm_context(self, run: Run, workspace: Workspace) -> Run:
        current = await self.rhythm.current(workspace.id)
        state = {
            "rhythm_snapshot": current.snapshot.model_dump(mode="json"),
            "rhythm_policy": current.policy.model_dump(mode="json"),
            "weather": current.weather.model_dump(mode="json"),
        }
        async with self.database.transaction() as connection:
            stored = await self.runs.get_in(connection, run.id)
            if stored is None:
                raise LookupError(run.id)
            if stored.rhythm_snapshot_id is not None:
                return stored
            updated = await self.runs.attach_rhythm_snapshot_in(
                connection,
                run.id,
                current.snapshot.id,
                stored.version,
            )
            checkpoint = await self.checkpoints.get_in(connection, run.id)
            if checkpoint is None:
                await self.checkpoints.create_in(
                    connection,
                    RunCheckpoint.new(
                        run_id=run.id,
                        transcript=(
                            AgentMessage(
                                role=MessageRole.USER,
                                content=run.user_intent,
                            ),
                        ),
                        state=state,
                    ),
                )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="run.rhythm_policy_bound",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=run.id,
                    correlation_id=run.id,
                    payload=state,
                ),
            )
        return updated

    @staticmethod
    def _orchestrator_prompt(policy: dict) -> str:
        return (
            "Complete the user's explicit goal with minimum added burden. "
            "RhythmPolicy changes interaction strategy but never changes the explicit "
            "user goal or bypasses Trust decisions. "
            f"interaction_budget={policy.get('interaction_budget', 'normal')}; "
            f"response_density={policy.get('response_density', 'normal')}; "
            f"delegation_bias={policy.get('delegation_bias', 'neutral')}; "
            f"scope_pressure={policy.get('scope_pressure', 'hold')}; "
            f"work_mode={policy.get('work_mode', 'normal')}; "
            f"proactivity={policy.get('proactivity', 'silent')}."
        )
