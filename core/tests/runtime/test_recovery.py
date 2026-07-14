from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.runs import RunStatus
from weatherflow.runtime import LoopStatus
from weatherflow.workspaces import Workspace


class RetryableFailureModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        raise TimeoutError("provider timeout with internal details")


async def test_retryable_model_failure_pauses_after_bounded_attempts(
    tmp_path: Path,
) -> None:
    model = RetryableFailureModel()
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path), model=model)

    run, outcome = await container.submit_run(
        user_intent="Complete safely",
        client_request_id="retry-model",
    )

    assert outcome is not None and outcome.status is LoopStatus.PAUSED
    assert model.calls == 3
    stored = await container.runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.PAUSED
    assert stored.result_summary is None
    events = await container.ledger.list_correlation(run.id, limit=1000)
    assert len([event for event in events if event.type == "runtime.model_retry"]) == 2
    assert events[-1].type == "run.status_changed"


async def test_corrupt_checkpoint_is_quarantined_and_run_needs_review(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    run, _ = await container.submit_run(
        user_intent="Recover this run",
        client_request_id="corrupt-checkpoint",
        execute=False,
    )
    async with container.database.transaction() as connection:
        await connection.execute(
            "UPDATE checkpoints SET state = '{not-json' WHERE run_id = ?", (run.id,)
        )

    outcome = await container.resume_run(run.id)

    assert outcome.status is LoopStatus.NEEDS_REVIEW
    stored = await container.runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.NEEDS_REVIEW
    async with container.database.connect() as connection:
        checkpoint = await (
            await connection.execute("SELECT 1 FROM checkpoints WHERE run_id = ?", (run.id,))
        ).fetchone()
        quarantine = await (
            await connection.execute(
                "SELECT reason, payload_sha256 FROM checkpoint_quarantine WHERE run_id = ?",
                (run.id,),
            )
        ).fetchone()
    assert checkpoint is None
    assert quarantine["reason"] == "checkpoint_validation_failed"
    assert len(quarantine["payload_sha256"]) == 64
    timeline = await container.ledger.list_correlation(run.id, limit=1000)
    assert any(event.type == "runtime.checkpoint_quarantined" for event in timeline)


async def test_restart_parks_recovered_run_when_model_is_not_configured(
    tmp_path: Path,
) -> None:
    first = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    run, _ = await first.submit_run(
        user_intent="Remain queued",
        client_request_id="startup-recovery",
        execute=False,
    )

    rebuilt = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    await rebuilt.start_background()
    try:
        stored = await rebuilt.wait_for_background_run(run.id, timeout_seconds=1)

        assert stored.status is RunStatus.WAITING_USER
        assert stored.error_class == "ModelConfigurationRequired"
        events = await rebuilt.ledger.list_correlation(run.id, limit=1000)
        audit = [event for event in events if event.type == "runtime.startup_recovery_audited"]
        assert len(audit) == 1
        assert audit[0].payload["decision"] == "scheduled_for_background_resume"
    finally:
        await rebuilt.stop_background()


async def test_missing_provider_is_recorded_for_new_run(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = Workspace.new(
        name="Personal",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:write", "calendar:read", "calendar:write"},
        installed_packs={"personal_operations"},
    )
    await container.workspaces.create(workspace)

    run, _ = await container.submit_run(
        user_intent="Prepare my meeting",
        client_request_id="provider-degraded",
        workspace_id=workspace.id,
        execute=False,
    )

    events = await container.ledger.list_correlation(run.id, limit=1000)
    degraded = [event for event in events if event.type == "provider.degraded"]
    assert len(degraded) == 1
    assert degraded[0].payload["tool_ids"] == [
        "calendar.create_event",
        "calendar.list_events",
        "personal.prepare_meeting",
        "personal.propose_schedule",
    ]
