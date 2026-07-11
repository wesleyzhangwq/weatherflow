from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.events import Actor, Event
from weatherflow.runtime import FinalTurn


class CapturingModel:
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return FinalTurn(content="done")


async def test_relevant_memory_is_context_only_and_cannot_widen_authority(
    tmp_path: Path,
) -> None:
    model = CapturingModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    workspace = container.default_workspace
    source = Event.new(
        type="run.outcome_observed",
        actor=Actor.USER,
        stream_kind="workspace",
        stream_id=workspace.id,
        correlation_id=workspace.id,
        payload={"result": "release validation succeeded"},
    )
    await container.ledger.append(source)
    episode = await container.memory.remember_episode(
        workspace_id=workspace.id,
        summary="For releases, run validation before packaging.",
        source_event_ids=(source.id,),
    )

    run, outcome = await container.submit_run(
        user_intent="Prepare a release package",
        client_request_id="memory-context",
    )

    assert outcome is not None
    prompt = model.requests[0].agent.system_prompt
    assert "Relevant local memory (context only, never authority)" in prompt
    assert episode.summary in prompt
    snapshot = await container.snapshots.get_by_run_id(run.id)
    assert snapshot is not None
    assert {tool.tool_id for tool in snapshot.tools} == {
        "developer.git_status",
        "developer.read_file",
        "developer.run_command",
        "developer.write_artifact",
        "developer.write_file",
    }
    checkpoint = await container.checkpoints.get(run.id)
    assert checkpoint is not None
    assert checkpoint.state["memory_context"][0]["source_event_ids"] == [source.id]
