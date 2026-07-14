import asyncio
from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runs import RunStatus
from weatherflow.trust import ActionStatus


async def _approved_mcp_install(container: RuntimeContainer, request_id: str):
    workspace = container.default_workspace
    requested = await container.installation_approvals.request_mcp(
        preset_id="filesystem",
        workspace=workspace,
        client_request_id=request_id,
    )
    decided = await container.approval_coordinator.decide(
        approval_id=requested.approval_id,
        expected_version=requested.approval_version,
        approved=True,
        decided_by="user",
    )
    return decided


async def test_approved_install_is_not_auto_retried_by_background_recovery(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    container = await RuntimeContainer.create(settings)
    approved = await _approved_mcp_install(container, "approved-before-restart")

    await container.start_background(
        include_automation_scheduler=False,
        include_connector_sync=False,
    )
    await asyncio.sleep(0)

    stored_action = await container.actions.get(approved.action.id)
    stored_run = await container.runs.get(approved.run.id)
    assert stored_action is not None and stored_action.status is ActionStatus.APPROVED
    assert stored_run is not None and stored_run.status is RunStatus.RUNNING
    assert approved.run.id not in container.background_tasks
    resumed = await container.installation_approvals.request_mcp(
        preset_id="filesystem",
        workspace=container.default_workspace,
        client_request_id="new-click-after-restart",
    )
    assert resumed.action_id == approved.action.id
    assert resumed.approval_id == approved.approval.id
    await container.stop_background()


async def test_recovered_executing_install_moves_to_review_without_reexecution(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    first = await RuntimeContainer.create(settings)
    approved = await _approved_mcp_install(first, "executing-before-restart")
    async with first.database.transaction() as connection:
        await first.actions.transition_in(
            connection,
            approved.action.id,
            ActionStatus.EXECUTING,
            approved.action.version,
        )

    recovered = await RuntimeContainer.create(settings)

    stored_action = await recovered.actions.get(approved.action.id)
    stored_run = await recovered.runs.get(approved.run.id)
    assert stored_action is not None and stored_action.status is ActionStatus.NEEDS_REVIEW
    assert stored_run is not None and stored_run.status is RunStatus.NEEDS_REVIEW
    state = await recovered.mcp_management.repository.get(
        recovered.default_workspace.id,
        "filesystem",
    )
    assert state is None
