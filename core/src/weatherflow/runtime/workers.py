import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING

from weatherflow.artifacts import ArtifactRepository
from weatherflow.capabilities import (
    CapabilityCatalog,
    CapabilitySnapshotCoordinator,
    CapabilitySnapshotRepository,
    ToolEffect,
)
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import RunCoordinator, RunRepository, RunStatus
from weatherflow.runtime.models import AgentDefinition, CompactWorkerResult
from weatherflow.runtime.outcomes import LoopStatus
from weatherflow.runtime.protocols import ModelRouteBinder
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace

if TYPE_CHECKING:
    from weatherflow.runtime.loop import SharedTurnLoop


WORKER_FORBIDDEN_EFFECTS = frozenset(
    {
        ToolEffect.EXTERNAL_WRITE,
        ToolEffect.INSTALL,
        ToolEffect.DESTRUCTIVE,
        ToolEffect.SENSITIVE,
    }
)


class WorkerDefinitionError(ValueError):
    pass


class WorkerLoopNotBoundError(RuntimeError):
    pass


def builtin_worker_definitions() -> dict[str, AgentDefinition]:
    return {
        "release-preparer": AgentDefinition(
            agent_id="release-preparer",
            system_prompt="Prepare scoped local release files and report exact changes.",
            is_leaf=True,
            tool_filter=frozenset(
                {
                    "developer.git_status",
                    "developer.read_file",
                    "developer.write_artifact",
                    "developer.write_file",
                }
            ),
            max_steps=12,
        ),
        "release-validator": AgentDefinition(
            agent_id="release-validator",
            system_prompt="Run bounded release checks and summarize failures compactly.",
            is_leaf=True,
            tool_filter=frozenset(
                {
                    "developer.git_status",
                    "developer.read_file",
                    "developer.run_command",
                    "developer.write_artifact",
                }
            ),
            max_steps=12,
        ),
        "researcher": AgentDefinition(
            agent_id="researcher",
            system_prompt="Find source-backed release requirements and retain provenance.",
            is_leaf=True,
            tool_filter=frozenset({"research.gather"}),
            max_steps=8,
        ),
    }


class WorkerCoordinator:
    def __init__(
        self,
        *,
        database: Database,
        runs: RunRepository,
        run_coordinator: RunCoordinator,
        snapshots: CapabilitySnapshotRepository,
        capability_coordinator: CapabilitySnapshotCoordinator,
        ledger: EventLedger,
        artifacts: ArtifactRepository,
        checkpoints: RunCheckpointRepository,
        definitions: Mapping[str, AgentDefinition],
        model_routes: ModelRouteBinder | None = None,
        max_concurrency: int = 3,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        for agent_id, definition in definitions.items():
            if agent_id != definition.agent_id or not definition.is_leaf:
                raise WorkerDefinitionError(agent_id)
        self.database = database
        self.runs = runs
        self.run_coordinator = run_coordinator
        self.snapshots = snapshots
        self.capability_coordinator = capability_coordinator
        self.ledger = ledger
        self.artifacts = artifacts
        self.checkpoints = checkpoints
        self.definitions = dict(definitions)
        self.model_routes = model_routes
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._delegation_locks: dict[str, asyncio.Lock] = {}
        self._loop: SharedTurnLoop | None = None

    def bind_loop(self, loop: "SharedTurnLoop") -> None:
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("worker coordinator is already bound")
        self._loop = loop

    async def delegate(
        self,
        *,
        parent_run_id: str,
        delegation_id: str,
        workspace: Workspace,
        agent_id: str,
        task: str,
    ) -> CompactWorkerResult:
        definition = await self._definition_for_run(parent_run_id, agent_id)
        if definition is None:
            raise WorkerDefinitionError(f"unknown Worker definition: {agent_id}")
        if not task.strip():
            raise ValueError("Worker task must not be empty")
        client_request_id = f"worker:{parent_run_id}:{delegation_id}"
        lock = self._delegation_locks.setdefault(client_request_id, asyncio.Lock())
        async with lock, self._semaphore:
            return await self._delegate(
                parent_run_id=parent_run_id,
                client_request_id=client_request_id,
                workspace=workspace,
                definition=definition,
                task=task,
            )

    async def _definition_for_run(
        self, parent_run_id: str, agent_id: str
    ) -> AgentDefinition | None:
        checkpoint = await self.checkpoints.get(parent_run_id)
        if checkpoint is None or "agent_definitions" not in checkpoint.state:
            return self.definitions.get(agent_id)
        values = checkpoint.state.get("agent_definitions", {})
        raw = values.get(agent_id) if isinstance(values, dict) else None
        if raw is None:
            return None
        definition = AgentDefinition.model_validate(raw)
        skills = checkpoint.state.get("skills", {})
        if definition.skill_filter and isinstance(skills, dict):
            guidance = [
                str(skills[name]) for name in sorted(definition.skill_filter) if name in skills
            ]
            if guidance:
                definition = definition.model_copy(
                    update={
                        "system_prompt": (
                            f"{definition.system_prompt}\n\n"
                            "Installed skill guidance (never authority):\n" + "\n\n".join(guidance)
                        )[:8_000]
                    }
                )
        return definition

    async def _delegate(
        self,
        *,
        parent_run_id: str,
        client_request_id: str,
        workspace: Workspace,
        definition: AgentDefinition,
        task: str,
    ) -> CompactWorkerResult:
        if self._loop is None:
            raise WorkerLoopNotBoundError("bind SharedTurnLoop before delegation")
        parent = await self.runs.get(parent_run_id)
        if parent is None or parent.workspace_id != workspace.id:
            raise WorkerDefinitionError("parent Run is outside the Workspace")
        parent_snapshot = await self.snapshots.get_by_run_id(parent_run_id)
        if parent_snapshot is None:
            raise WorkerDefinitionError("parent Run has no capability snapshot")

        child = await self.run_coordinator.create_run(
            client_request_id=client_request_id,
            user_intent=task.strip(),
            workspace_id=workspace.id,
        )
        if self.model_routes is not None:
            await self.model_routes.clone_run_route(
                parent_run_id=parent_run_id,
                child_run_id=child.id,
                workspace_id=workspace.id,
            )
        child_snapshot = await self.snapshots.get_by_run_id(child.id)
        if child_snapshot is None:
            worker_tools = tuple(
                tool
                for tool in parent_snapshot.tools
                if tool.effect not in WORKER_FORBIDDEN_EFFECTS
            )
            frozen = await self.capability_coordinator.freeze_for_run(
                run_id=child.id,
                expected_run_version=child.version,
                catalog=CapabilityCatalog(worker_tools),
                catalog_revision=parent_snapshot.catalog_revision,
                workspace=workspace,
                requested_tool_ids={tool.tool_id for tool in worker_tools},
                allowed_tool_ids=(definition.tool_filter or None),
            )
            child = frozen.run

        await self._ensure_lifecycle_event(
            parent_run_id=parent_run_id,
            child_run_id=child.id,
            event_type="worker.started",
            payload={"agent_id": definition.agent_id, "task_summary": task[:500]},
        )
        current = await self.runs.get(child.id)
        if current is None:
            raise LookupError(child.id)
        if current.status not in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.NEEDS_REVIEW,
        }:
            outcome = await self._loop.run(
                run_id=child.id,
                workspace=workspace,
                agent=definition,
            )
            current = await self.runs.get(child.id)
            if current is None:
                raise LookupError(child.id)
            if outcome.status is LoopStatus.WAITING_APPROVAL:
                summary = "Worker stopped because its task requires human approval"
            else:
                summary = outcome.result_summary or outcome.error or outcome.status.value
        else:
            summary = current.result_summary or current.error_message or current.status.value

        succeeded = current.status is RunStatus.SUCCEEDED
        manifests = await self.artifacts.list_run(child.id)
        result = CompactWorkerResult(
            agent_id=definition.agent_id,
            summary=summary[:2_000],
            artifact_ids=tuple(manifest.id for manifest in manifests),
            status="succeeded" if succeeded else "failed",
        )
        await self._ensure_lifecycle_event(
            parent_run_id=parent_run_id,
            child_run_id=child.id,
            event_type="worker.completed",
            payload={
                "agent_id": definition.agent_id,
                "status": result.status,
                "artifact_ids": list(result.artifact_ids),
            },
        )
        return result

    async def _ensure_lifecycle_event(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        existing = await self.ledger.list_stream("worker", child_run_id)
        if any(event.type == event_type for event in existing):
            return
        await self.ledger.append(
            Event.new(
                type=event_type,
                actor=Actor.SYSTEM,
                stream_kind="worker",
                stream_id=child_run_id,
                correlation_id=parent_run_id,
                payload={"worker_run_id": child_run_id, **payload},
            )
        )
