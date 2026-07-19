import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities.builtin import GitHubRelease, ResearchSource
from weatherflow.config import Settings
from weatherflow.rhythm import CheckInSignal
from weatherflow.runs import ToolMode
from weatherflow.runtime import DelegationTurn, FinalTurn, ToolCallTurn
from weatherflow.workspaces import Workspace

from .models import TrajectoryReport
from .trajectory import FlagshipTrajectoryEvaluator


class FlagshipFixtureResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    report: TrajectoryReport
    release_calls_before_approval: int
    release_calls_after_approval: int
    release_calls_after_replay: int
    model_calls_after_completion: int
    model_calls_after_replay: int


class FixtureResearchProvider:
    async def search(self, query: str, *, limit: int) -> tuple[ResearchSource, ...]:
        return (
            ResearchSource(
                title="Notarizing macOS software",
                url="https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution",
                excerpt="Signed software should be submitted for notarization.",
                retrieved_at=datetime.now(UTC),
            ),
            ResearchSource(
                title="WeatherFlow release policy",
                url="https://example.test/weatherflow-release-policy",
                excerpt="Run validation before creating the release.",
                retrieved_at=datetime.now(UTC),
            ),
        )[:limit]


class FixtureGitHubProvider:
    def __init__(self) -> None:
        self.release_calls: list[str] = []

    async def inspect_release(self, *, repository: str, tag: str) -> GitHubRelease | None:
        return None

    async def create_release(
        self,
        *,
        repository: str,
        tag: str,
        name: str,
        body: str,
        idempotency_key: str,
    ) -> GitHubRelease:
        self.release_calls.append(idempotency_key)
        return GitHubRelease(
            repository=repository,
            tag=tag,
            status="published",
            url="https://example.test/wesz/weatherflow/releases/v3.0.0",
        )


class RecordedFlagshipModel:
    def __init__(self) -> None:
        self.steps: defaultdict[str, int] = defaultdict(int)
        self.call_count = 0

    async def complete(self, request):
        self.call_count += 1
        agent_id = request.agent.agent_id
        step = self.steps[agent_id]
        self.steps[agent_id] += 1
        if agent_id == "orchestrator":
            return self._orchestrator(step)
        if agent_id == "release-preparer":
            return self._release_preparer(step)
        if agent_id == "researcher":
            return self._researcher(step)
        if agent_id == "release-validator":
            return self._release_validator(step)
        raise LookupError(agent_id)

    @staticmethod
    def _orchestrator(step: int):
        turns = (
            DelegationTurn(
                agent_id="release-preparer",
                task="Prepare a minimal release checklist and release notes.",
            ),
            DelegationTurn(
                agent_id="researcher",
                task="Research current macOS release and notarization requirements.",
            ),
            DelegationTurn(
                agent_id="release-validator",
                task="Run the bounded release validation and retain its evidence.",
            ),
            ToolCallTurn(
                call_id="publish-v3",
                tool_id="github.create_release",
                arguments={
                    "repository": "wesz/weatherflow",
                    "tag": "v3.0.0",
                    "name": "WeatherFlow v3",
                    "body": "Validated by the WeatherFlow flagship trajectory.",
                },
            ),
            FinalTurn(content="Release preparation completed with validated artifacts."),
        )
        return turns[step]

    @staticmethod
    def _release_preparer(step: int):
        turns = (
            ToolCallTurn(
                tool_id="developer.write_file",
                arguments={
                    "path": "RELEASE_NOTES.md",
                    "content": "# WeatherFlow v3\n\nValidated flagship release.\n",
                },
            ),
            ToolCallTurn(
                tool_id="developer.write_artifact",
                arguments={
                    "name": "release-checklist.md",
                    "media_type": "text/markdown",
                    "content": "# Release checklist\n- notes prepared\n- scope reduced\n",
                    "validation": {"status": "passed", "checks": 2},
                },
            ),
            FinalTurn(content="Prepared scoped release notes and checklist."),
        )
        return turns[step]

    @staticmethod
    def _researcher(step: int):
        turns = (
            ToolCallTurn(
                tool_id="research.gather",
                arguments={"query": "macOS notarization release requirements", "limit": 5},
            ),
            FinalTurn(content="Captured source-backed notarization requirements."),
        )
        return turns[step]

    @staticmethod
    def _release_validator(step: int):
        turns = (
            ToolCallTurn(
                tool_id="developer.read_file",
                arguments={"path": "RELEASE_NOTES.md"},
            ),
            ToolCallTurn(
                tool_id="developer.write_artifact",
                arguments={
                    "name": "validation-report.md",
                    "media_type": "text/markdown",
                    "content": "# Validation\n\nAll deterministic checks passed.\n",
                    "validation": {"status": "passed", "checks": 1},
                },
            ),
            FinalTurn(content="Validation passed and evidence was retained."),
        )
        return turns[step]


async def run_flagship_fixture(data_dir: Path) -> FlagshipFixtureResult:
    model = RecordedFlagshipModel()
    github = FixtureGitHubProvider()
    container = await RuntimeContainer.create(
        Settings(data_dir=data_dir),
        model=model,
        research_provider=FixtureResearchProvider(),
        github_provider=github,
    )
    project = data_dir / "flagship-project"
    await asyncio.to_thread(project.mkdir, parents=True, exist_ok=True)
    workspace = Workspace.new(
        name="Flagship",
        action_roots=[project],
        internal_root=data_dir / "flagship-internal",
        artifact_root=data_dir / "flagship-artifacts",
        granted_scopes={
            "workspace:read",
            "workspace:write",
            "workspace:execute",
            "network:read",
            "github:read",
            "github:write",
        },
        installed_packs={"developer", "research"},
    )
    await container.workspaces.create(workspace)
    await container.rhythm.ingest(
        workspace.id,
        CheckInSignal(
            text="I am overloaded and exhausted, but this version still has to ship.",
            observed_at=datetime.now(UTC),
        ),
    )
    run, waiting = await container.submit_run(
        user_intent=(
            "I am already overloaded, but this version still has to ship. "
            "Complete release preparation with the least additional burden."
        ),
        client_request_id="flagship-release-v3",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )
    if waiting is None or waiting.approval_id is None:
        raise RuntimeError("flagship trajectory did not park for approval")
    before = len(github.release_calls)
    approval = await container.approvals.get(waiting.approval_id)
    if approval is None:
        raise RuntimeError(waiting.approval_id)
    await container.approval_coordinator.decide(
        approval_id=approval.id,
        expected_version=approval.version,
        approved=True,
        decided_by="user",
        rationale="Release preview and validation look correct.",
    )
    completed = await container.resume_run(run.id)
    if completed.result_summary is None:
        raise RuntimeError("flagship trajectory did not complete")
    after_approval = len(github.release_calls)
    model_calls_after_completion = model.call_count
    await container.submit_run(
        user_intent="retry must reuse the durable Run",
        client_request_id="flagship-release-v3",
        workspace_id=workspace.id,
        tool_mode=ToolMode.BYPASS,
    )
    after_replay = len(github.release_calls)
    report = await FlagshipTrajectoryEvaluator().evaluate(
        container=container,
        run_id=run.id,
        release_calls_before_approval=before,
        release_calls_after_approval=after_approval,
        release_calls_after_replay=after_replay,
    )
    return FlagshipFixtureResult(
        report=report,
        release_calls_before_approval=before,
        release_calls_after_approval=after_approval,
        release_calls_after_replay=after_replay,
        model_calls_after_completion=model_calls_after_completion,
        model_calls_after_replay=model.call_count,
    )
