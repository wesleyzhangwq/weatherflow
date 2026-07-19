import asyncio
import hashlib
import json
from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.runs import RunStatus
from weatherflow.runtime import MessageRole

from .models import TrajectoryCheck, TrajectoryReport


class FlagshipTrajectoryEvaluator:
    async def evaluate(
        self,
        *,
        container: RuntimeContainer,
        run_id: str,
        release_calls_before_approval: int,
        release_calls_after_approval: int,
        release_calls_after_replay: int,
    ) -> TrajectoryReport:
        run = await container.runs.get(run_id)
        if run is None:
            raise LookupError(run_id)
        workspace = await container.workspaces.get(run.workspace_id)
        if workspace is None:
            raise LookupError(run.workspace_id)
        timeline = await container.ledger.list_correlation(run_id, limit=1000)
        event_types = [event.type for event in timeline]
        policy_events = [event for event in timeline if event.type == "run.rhythm_policy_bound"]
        worker_events = [event for event in timeline if event.type == "worker.completed"]
        worker_run_ids = tuple(
            dict.fromkeys(str(event.payload["worker_run_id"]) for event in worker_events)
        )
        artifacts = await container.run_artifacts(run_id)
        checks: list[TrajectoryCheck] = []

        self._check(
            checks,
            "terminal_success",
            run.status is RunStatus.SUCCEEDED,
            status=run.status.value,
        )
        policy = policy_events[0].payload.get("rhythm_policy", {}) if policy_events else {}
        self._check(
            checks,
            "overload_strategy_bound",
            len(policy_events) == 1
            and policy.get("interaction_budget") == "minimal"
            and policy.get("response_density") == "compact"
            and policy.get("delegation_bias") == "favor"
            and policy.get("scope_pressure") == "reduce"
            and policy.get("proactivity") == "silent",
            policy=policy,
        )
        snapshot = await container.snapshots.get_by_run_id(run_id)
        tool_ids = [tool.tool_id for tool in snapshot.tools] if snapshot else []
        self._check(
            checks,
            "frozen_capability_surface",
            snapshot is not None
            and "developer.write_file" in tool_ids
            and "research.gather" in tool_ids
            and "github.create_release" in tool_ids,
            tool_ids=tool_ids,
        )
        worker_agents = {str(event.payload.get("agent_id")) for event in worker_events}
        expected_workers = {"release-preparer", "release-validator", "researcher"}
        child_nested_events = [
            event
            for worker_run_id in worker_run_ids
            for event in await container.ledger.list_correlation(worker_run_id, limit=1000)
            if event.type == "worker.started"
        ]
        self._check(
            checks,
            "leaf_worker_set",
            worker_agents == expected_workers
            and len(worker_run_ids) == 3
            and not child_nested_events
            and all(
                container.workers.definitions[agent_id].is_leaf for agent_id in expected_workers
            ),
            agents=sorted(worker_agents),
            child_run_ids=list(worker_run_ids),
        )

        approval_order = self._ordered(
            event_types,
            [
                "approval.requested",
                "approval.decided",
                "action.execution_started",
                "action.execution_succeeded",
            ],
        )
        self._check(
            checks,
            "approval_before_external_execution",
            approval_order
            and event_types.count("action.execution_started") == 1
            and release_calls_before_approval == 0
            and release_calls_after_approval == 1
            and release_calls_after_replay == 1,
            release_calls=[
                release_calls_before_approval,
                release_calls_after_approval,
                release_calls_after_replay,
            ],
        )

        artifacts_valid = bool(artifacts)
        for artifact in artifacts:
            path = Path(workspace.artifact_root) / artifact.relative_path
            data = await asyncio.to_thread(path.read_bytes)
            events = await container.ledger.list_correlation(artifact.run_id, limit=1000)
            artifacts_valid = artifacts_valid and (
                hashlib.sha256(data).hexdigest() == artifact.digest
                and any(
                    event.type == "artifact.created" and event.stream_id == artifact.id
                    for event in events
                )
                and bool(artifact.validation)
            )
        validation_kinds = {
            str(artifact.validation.get("kind") or artifact.validation.get("status"))
            for artifact in artifacts
        }
        self._check(
            checks,
            "artifact_provenance_and_validation",
            len(artifacts) >= 3
            and artifacts_valid
            and "source-backed-research" in validation_kinds
            and "passed" in validation_kinds,
            artifact_ids=[artifact.id for artifact in artifacts],
            validation_kinds=sorted(validation_kinds),
        )

        task_events = [event for event in timeline if event.type == "rhythm.signal.task_behavior"]
        result_index = (
            event_types.index("run.result_committed")
            if "run.result_committed" in event_types
            else -1
        )
        task_index = event_types.index("rhythm.signal.task_behavior") if task_events else -1
        self._check(
            checks,
            "terminal_behavior_appended",
            len(task_events) == 1
            and task_index > result_index
            and task_events[0].payload["signal"]["outcome"] == "succeeded",
            count=len(task_events),
        )
        failure_types = {
            "action.needs_review",
            "action.execution_failed",
        }
        worker_tool_errors: list[str] = []
        for worker_run_id in worker_run_ids:
            checkpoint = await container.checkpoints.get(worker_run_id)
            if checkpoint is None:
                worker_tool_errors.append("missing_checkpoint")
                continue
            for message in checkpoint.transcript:
                if message.role is not MessageRole.TOOL:
                    continue
                try:
                    observation = json.loads(message.content)
                except json.JSONDecodeError:
                    worker_tool_errors.append("invalid_observation")
                    continue
                if isinstance(observation, dict) and observation.get("error"):
                    worker_tool_errors.append(str(observation["error"]))
        self._check(
            checks,
            "no_false_success_or_ambiguous_side_effect",
            not failure_types.intersection(event_types) and not worker_tool_errors,
            observed=sorted(failure_types.intersection(event_types)),
            worker_tool_errors=worker_tool_errors,
        )
        return TrajectoryReport(
            run_id=run_id,
            passed=all(check.passed for check in checks),
            checks=tuple(checks),
            metrics={
                "worker_count": len(worker_run_ids),
                "artifact_count": len(artifacts),
                "timeline_event_count": len(timeline),
            },
        )

    @staticmethod
    def _ordered(haystack: list[str], needles: list[str]) -> bool:
        positions: list[int] = []
        start = 0
        for needle in needles:
            try:
                position = haystack.index(needle, start)
            except ValueError:
                return False
            positions.append(position)
            start = position + 1
        return positions == sorted(positions)

    @staticmethod
    def _check(
        checks: list[TrajectoryCheck],
        name: str,
        passed: bool,
        **evidence,
    ) -> None:
        checks.append(TrajectoryCheck(name=name, passed=passed, evidence=evidence))
