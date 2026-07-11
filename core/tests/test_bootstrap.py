from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runs import RunStatus
from weatherflow.runtime import LoopStatus


async def test_runtime_container_rebuilds_from_same_data_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    first = await RuntimeContainer.create(settings)
    workspace = first.default_workspace

    run, outcome = await first.submit_run(
        user_intent="Explain WeatherFlow",
        client_request_id="request-1",
    )

    assert outcome is not None and outcome.status is LoopStatus.SUCCEEDED
    assert run.workspace_id == workspace.id

    rebuilt = await RuntimeContainer.create(settings)
    stored_workspace = await rebuilt.workspaces.get(workspace.id)
    stored_run = await rebuilt.runs.get(run.id)
    snapshot = await rebuilt.snapshots.get_by_run_id(run.id)
    checkpoint = await rebuilt.checkpoints.get(run.id)

    assert stored_workspace == workspace
    assert stored_run is not None and stored_run.status is RunStatus.SUCCEEDED
    assert snapshot is not None and snapshot.tools == ()
    assert checkpoint is not None and checkpoint.state == {"result_committed": True}


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
