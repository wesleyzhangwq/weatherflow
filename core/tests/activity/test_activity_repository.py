from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.activity import (
    ACTIVITY_SUMMARY_PROMPT_VERSION,
    ActivityEvidenceRef,
    ActivityRepository,
    ActivitySourceHealth,
    ActivitySourceState,
    ActivityStatistics,
    ActivitySummaryRevision,
    ActivitySummarySettings,
    ActivityWindowPlanner,
    ModelResponseFailureStage,
    SummaryFinality,
    SummaryTaskStatus,
    SummaryTaskType,
    category_rule_version,
)
from weatherflow.activity.repository import StaleActivitySummaryAttempt
from weatherflow.storage import Database


async def setup_repository(tmp_path: Path) -> ActivityRepository:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    return ActivityRepository(database)


def evidence() -> ActivityEvidenceRef:
    return ActivityEvidenceRef(
        activitywatch_server_id="device-1",
        bucket_id="window",
        event_id="1",
        event_timestamp=datetime(2026, 7, 16, 0, tzinfo=UTC),
        event_duration=60,
        event_digest="e" * 64,
        fields_used=("application", "title"),
    )


def revision(task_id: str, *, generation_id: str, text: str) -> ActivitySummaryRevision:
    stats = ActivityStatistics(
        window_start=datetime(2026, 7, 16, 0, tzinfo=UTC),
        window_end=datetime(2026, 7, 16, 6, tzinfo=UTC),
        active_seconds=60,
        application_seconds={"Code": 60},
        category_seconds={"Work / Programming": 60},
        source_watermark="w" * 64,
    )
    return ActivitySummaryRevision(
        id="pending",
        task_id=task_id,
        revision_number=1,
        generation_id=generation_id,
        finality=SummaryFinality.FINAL,
        statistics=stats,
        summary_text=text,
        evidence_refs=(evidence(),),
        category_rule_version="c" * 64,
        category_rules_json="[]",
        provider="openai",
        model="gpt-test",
        configuration_version=3,
        prompt_version="prompt-v1",
        statistics_version=stats.statistics_version,
        request_digest="r" * 64,
        source_watermark=stats.source_watermark,
        completed_at=datetime(2026, 7, 16, 7, tzinfo=UTC),
    )


async def prepared_task(tmp_path: Path):
    repository = await setup_repository(tmp_path)
    now = datetime(2026, 7, 16, 7, tzinfo=UTC)
    rules = category_rule_version([{"name": ["Work"], "rule": {"type": "regex", "regex": "Code"}}])
    rules = rules.model_copy(update={"id": "c" * 64})
    await repository.save_category_rule_version(rules, now=now)
    await repository.save_source_state(
        ActivitySourceState(
            health=ActivitySourceHealth.AVAILABLE,
            checked_at=now,
            server_id="device-1",
            category_rule_version=rules.id,
        )
    )
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=datetime(2026, 7, 16, 0, tzinfo=UTC),
        window_end=datetime(2026, 7, 16, 6, tzinfo=UTC),
        created_at=now,
    )
    assert await repository.ensure_tasks([task]) == 1
    return repository, task, now


async def test_task_attempt_and_revision_round_trip(tmp_path: Path) -> None:
    repository, task, now = await prepared_task(tmp_path)
    claimed, attempt = await repository.claim_task(
        task.id,
        lease_owner="worker-1",
        now=now,
        category_rule_version="c" * 64,
    )
    completed, stored = await repository.complete_attempt(
        task_id=task.id,
        attempt_id=attempt.id,
        revision=revision(task.id, generation_id=attempt.id, text="Final narrative."),
        now=now,
    )

    assert claimed.attempt_count == 1
    assert completed.status is SummaryTaskStatus.COMPLETED
    assert completed.completed_at == now
    assert completed.error_code is None
    assert stored.summary_text == "Final narrative."
    assert stored.model == "gpt-test"
    assert stored.prompt_version == "prompt-v1"
    assert (await repository.list_attempts(task.id))[0].status.value == "completed"


async def test_summary_settings_change_requeues_completed_tasks(tmp_path: Path) -> None:
    repository, task, now = await prepared_task(tmp_path)
    _, attempt = await repository.claim_task(
        task.id,
        lease_owner="worker-1",
        now=now,
        category_rule_version="c" * 64,
    )
    await repository.complete_attempt(
        task_id=task.id,
        attempt_id=attempt.id,
        revision=revision(task.id, generation_id=attempt.id, text="Final narrative."),
        now=now,
    )
    settings = ActivitySummarySettings(
        model_workspace_id="legacy-default-workspace",
        provider="minimax",
        model="MiniMax-M3",
        model_configuration_version=1,
        prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
        version=0,
        updated_at=now,
    )
    await repository.ensure_summary_settings(settings)

    await repository.save_summary_settings(
        settings.model_copy(
            update={
                "model_workspace_id": "current-workspace",
                "model_configuration_version": 2,
            }
        ),
        expected_version=0,
        now=now + timedelta(minutes=1),
    )

    requeued = await repository.get_task(task.id)
    assert requeued is not None
    assert requeued.status is SummaryTaskStatus.NEEDS_RETRY
    assert requeued.next_retry_at == now + timedelta(minutes=1)
    assert requeued.completed_at is None
    assert requeued.regeneration_reason == "summary_settings_changed"


async def test_permanent_failure_is_not_automatically_due_but_can_regenerate(
    tmp_path: Path,
) -> None:
    repository, task, now = await prepared_task(tmp_path)
    _, attempt = await repository.claim_task(
        task.id,
        lease_owner="worker-1",
        now=now,
        category_rule_version="c" * 64,
    )
    failed = await repository.fail_attempt(
        task_id=task.id,
        attempt_id=attempt.id,
        error_code="validation_failed",
        now=now,
        retryable=False,
        failure_stage=ModelResponseFailureStage.MESSAGE,
    )

    assert failed.status is SummaryTaskStatus.FAILED
    attempts = await repository.list_attempts(task.id)
    assert attempts[-1].failure_stage is ModelResponseFailureStage.MESSAGE
    assert (
        await repository.list_due_tasks(
            now=now + timedelta(days=1),
            category_rule_version="c" * 64,
        )
        == []
    )
    regenerated = await repository.request_regeneration(
        task.id,
        now=now + timedelta(days=1),
        reason="user requested a new model revision",
    )
    assert regenerated.status is SummaryTaskStatus.NEEDS_RETRY
    assert (
        await repository.list_due_tasks(
            now=now + timedelta(days=1),
            category_rule_version="c" * 64,
        )
    )[0].id == task.id


async def test_completed_task_with_legacy_category_rules_is_due_from_ledger(
    tmp_path: Path,
) -> None:
    repository, task, now = await prepared_task(tmp_path)
    claimed = await repository.claim_task(
        task.id,
        lease_owner="worker-1",
        now=now,
        category_rule_version="c" * 64,
    )
    assert claimed is not None
    _, attempt = claimed
    await repository.complete_attempt(
        task_id=task.id,
        attempt_id=attempt.id,
        revision=revision(task.id, generation_id=attempt.id, text="Old rules."),
        now=now,
    )

    due = await repository.list_due_tasks(
        now=now,
        category_rule_version="d" * 64,
    )

    assert [item.id for item in due] == [task.id]


async def test_completed_provisional_task_becomes_due_at_final_retry_boundary(
    tmp_path: Path,
) -> None:
    repository, task, now = await prepared_task(tmp_path)
    claimed = await repository.claim_task(
        task.id,
        lease_owner="worker-1",
        now=now,
        category_rule_version="c" * 64,
    )
    assert claimed is not None
    _, attempt = claimed
    retry_at = now + timedelta(minutes=15)
    provisional = revision(
        task.id,
        generation_id=attempt.id,
        text="Provisional.",
    ).model_copy(update={"finality": SummaryFinality.PROVISIONAL})
    await repository.complete_attempt(
        task_id=task.id,
        attempt_id=attempt.id,
        revision=provisional,
        now=now,
        next_retry_at=retry_at,
    )

    assert (
        await repository.list_due_tasks(
            now=retry_at - timedelta(seconds=1),
            category_rule_version="c" * 64,
        )
        == []
    )
    due = await repository.list_due_tasks(
        now=retry_at,
        category_rule_version="c" * 64,
    )
    assert [item.id for item in due] == [task.id]


async def test_expired_worker_is_fenced_after_new_attempt_is_claimed(
    tmp_path: Path,
) -> None:
    repository, task, now = await prepared_task(tmp_path)
    _, first = await repository.claim_task(
        task.id,
        lease_owner="old-process",
        now=now,
        category_rule_version="c" * 64,
    )
    await repository.recover_expired_leases(now=now, include_unexpired=True)
    _, second = await repository.claim_task(
        task.id,
        lease_owner="new-process",
        now=now,
        category_rule_version="c" * 64,
    )

    with pytest.raises(StaleActivitySummaryAttempt):
        await repository.complete_attempt(
            task_id=task.id,
            attempt_id=first.id,
            revision=revision(task.id, generation_id=first.id, text="stale"),
            now=now,
        )

    current = await repository.get_task(task.id)
    assert current is not None
    assert current.status is SummaryTaskStatus.RUNNING
    assert current.attempt_count == second.attempt_number


async def test_revision_numbers_remain_monotonic_when_content_returns_to_old_value(
    tmp_path: Path,
) -> None:
    repository, task, now = await prepared_task(tmp_path)
    stored = []
    for index, text in enumerate(("Category A", "Category B", "Category A"), start=1):
        if index > 1:
            await repository.request_regeneration(
                task.id,
                now=now + timedelta(minutes=index),
                reason=f"category rules revision {index}",
            )
        claimed = await repository.claim_task(
            task.id,
            lease_owner=f"worker-{index}",
            now=now + timedelta(minutes=index),
            category_rule_version="c" * 64,
        )
        assert claimed is not None
        _claimed_task, attempt = claimed
        _completed, current = await repository.complete_attempt(
            task_id=task.id,
            attempt_id=attempt.id,
            revision=revision(
                task.id,
                generation_id=attempt.id,
                text=text,
            ),
            now=now + timedelta(minutes=index),
        )
        stored.append(current)

    assert [item.revision_number for item in stored] == [1, 2, 3]
    assert [item.summary_text for item in stored] == [
        "Category A",
        "Category B",
        "Category A",
    ]
    current_task = await repository.get_task(task.id)
    assert current_task is not None
    assert current_task.current_revision == 3


async def test_history_reset_preserves_cutoff_tombstone(tmp_path: Path) -> None:
    repository, task, now = await prepared_task(tmp_path)
    assert await repository.history_count() == 1

    deleted = await repository.reset_history(now=now + timedelta(minutes=30))

    assert deleted == 1
    assert await repository.history_count() == 0
    assert await repository.get_task(task.id) is None
    state = await repository.source_state()
    assert state is not None
    assert state.history_cutoff == now + timedelta(minutes=30)
    cleared = await repository.clear_history_cutoff(now=now + timedelta(hours=1))
    assert cleared.history_cutoff is None


async def test_stale_source_state_save_cannot_roll_back_history_cutoff(
    tmp_path: Path,
) -> None:
    repository, _task, now = await prepared_task(tmp_path)
    stale = await repository.source_state()
    assert stale is not None
    cutoff = now + timedelta(minutes=30)
    await repository.reset_history(now=cutoff)

    await repository.save_source_state(
        stale.model_copy(
            update={
                "checked_at": cutoff + timedelta(minutes=1),
            }
        )
    )

    current = await repository.source_state()
    assert current is not None
    assert current.history_cutoff == cutoff
    old_task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=cutoff - timedelta(hours=6),
        window_end=cutoff,
        created_at=cutoff + timedelta(hours=1),
    )
    new_task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=cutoff,
        window_end=cutoff + timedelta(hours=6),
        created_at=cutoff + timedelta(hours=7),
    )
    assert await repository.ensure_tasks([old_task, new_task]) == 1
    assert await repository.get_task(old_task.id) is None
    assert await repository.get_task(new_task.id) is not None
