import asyncio
from pathlib import Path

import pytest

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request):
        self.started.set()
        await self.release.wait()
        raise AssertionError("the runtime should cancel this model call during close")


async def test_close_cancels_and_awaits_every_tracked_run(tmp_path: Path) -> None:
    model = BlockingModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)
    run, _ = await container.submit_run(
        user_intent="Keep working until shutdown",
        client_request_id="background-close",
        execute=False,
    )
    await container.start_background(
        include_connector_sync=False,
        include_automation_scheduler=False,
    )
    await asyncio.wait_for(model.started.wait(), timeout=1)
    task = container.background_tasks[run.id]

    await container.close()

    assert task.cancelled()
    assert container.background_tasks == {}
    assert container.background_started is False
    await container.await_background()
    with pytest.raises(RuntimeError, match="closed"):
        container.schedule_run(run.id)


async def test_close_releases_runtime_owned_http_clients(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    model_client = container.model_configurations.client
    connector_client = container.connector_gateway.client

    await container.close()

    assert model_client is not None and model_client.is_closed
    assert connector_client.is_closed
