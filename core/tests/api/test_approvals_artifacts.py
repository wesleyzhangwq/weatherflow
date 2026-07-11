from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import CapabilityCatalog, ToolEffect, ToolSpec
from weatherflow.config import Settings
from weatherflow.runtime import FinalTurn, ToolCallTurn, ToolExecutionResult
from weatherflow.workspaces import Workspace


class ScriptedModel:
    def __init__(self):
        self.turns = [
            ToolCallTurn(
                call_id="release-v3",
                tool_id="github.create_release",
                arguments={"tag": "v3.0.0"},
            ),
            FinalTurn(content="Release shipped"),
        ]

    async def complete(self, request):
        return self.turns.pop(0)


class ReleaseExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, tool, arguments, context):
        self.calls += 1
        return ToolExecutionResult(output={"url": "https://example.test/v3"})


async def test_approval_decision_resumes_run_and_artifact_is_readable(
    tmp_path: Path,
) -> None:
    release = ToolSpec(
        tool_id="github.create_release",
        description="Create release",
        input_schema={},
        output_schema={},
        effect=ToolEffect.EXTERNAL_WRITE,
        required_scopes=frozenset({"github:write"}),
        source="test",
        source_version="1",
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=tmp_path),
        model=ScriptedModel(),
        catalog=CapabilityCatalog([release]),
    )
    workspace = Workspace.new(
        name="Release",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "release-internal",
        artifact_root=tmp_path / "release-artifacts",
        granted_scopes={"github:write"},
    )
    await container.workspaces.create(workspace)
    executor = ReleaseExecutor()
    container.executors.register(release.tool_id, executor)
    run, waiting = await container.submit_run(
        user_intent="Ship v3",
        client_request_id="request-1",
        workspace_id=workspace.id,
    )
    assert waiting is not None and waiting.approval_id is not None
    transport = ASGITransport(app=create_app(container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pending = await client.get("/v1/approvals", params={"approval_status": "pending"})
        decided = await client.post(
            f"/v1/approvals/{waiting.approval_id}/decision",
            json={"decision": "approve", "expected_version": 0, "resume": True},
        )
        artifact = await container.artifact_store.put_bytes(
            run_id=run.id,
            workspace=workspace,
            name="release.txt",
            media_type="text/plain",
            data=b"shipped",
        )
        metadata = await client.get(f"/v1/artifacts/{artifact.id}")
        content = await client.get(f"/v1/artifacts/{artifact.id}/content")
        timeline = await client.get(f"/v1/runs/{run.id}/timeline")

    assert pending.status_code == 200 and len(pending.json()) == 1
    assert pending.json()[0]["tool_id"] == "github.create_release"
    assert pending.json()[0]["effect"] == "external_write"
    assert pending.json()[0]["preview"] == {
        "tool_id": "github.create_release",
        "arguments": {"tag": "v3.0.0"},
    }
    assert decided.status_code == 200
    assert decided.json()["action"]["status"] == "succeeded"
    assert decided.json()["run"]["status"] == "succeeded"
    assert executor.calls == 1
    assert metadata.json()["digest"] == artifact.digest
    assert content.content == b"shipped"
    event_types = [event["type"] for event in timeline.json()]
    assert "approval.requested" in event_types
    assert "approval.decided" in event_types
    assert "action.execution_started" in event_types
    assert "action.execution_succeeded" in event_types
    assert "run.result_committed" in event_types
