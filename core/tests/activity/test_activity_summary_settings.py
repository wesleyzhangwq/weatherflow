import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.activity import (
    ACTIVITY_SUMMARY_PROMPT_VERSION,
    ACTIVITY_SUMMARY_SYSTEM_PROMPT,
    ActivityAnalysisRoute,
    ActivityCoverageStatus,
    ActivityModelOutputRejectedError,
    ActivityRepository,
    ActivitySourceHealth,
    ActivitySourceState,
    ActivityStatistics,
    ActivitySummaryAnalyzer,
    ActivitySummaryService,
    ActivitySummarySettings,
    ActivitySummarySettingsVersionConflict,
    ActivityWindowEvidence,
    ActivityWindowPlanner,
    ObservedActivityFact,
    SummaryTaskType,
    category_rule_version,
)
from weatherflow.connectors import (
    CONNECTOR_DEFINITIONS,
    ConnectorFeed,
    ConnectorFeedHealth,
    ConnectorFeedItem,
    ConnectorFeedSource,
    ConnectorKind,
)
from weatherflow.models import MiniMaxAuthenticationError
from weatherflow.runtime import FinalTurn
from weatherflow.storage import Database


async def test_activity_summary_settings_only_persist_model_selection(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    repository = ActivityRepository(database)
    now = datetime(2026, 7, 18, 1, 0, tzinfo=UTC)
    initial = ActivitySummarySettings(
        model_workspace_id="workspace-1",
        provider="minimax",
        model="MiniMax-M3",
        model_configuration_version=4,
        prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
        version=0,
        updated_at=now,
    )

    assert await repository.ensure_summary_settings(initial) == initial
    changed = await repository.save_summary_settings(
        initial.model_copy(update={"model": "MiniMax-M3-fast"}),
        expected_version=0,
        now=now,
    )

    assert changed.version == 1
    assert changed.model == "MiniMax-M3-fast"
    assert changed.prompt_version == ACTIVITY_SUMMARY_PROMPT_VERSION
    with pytest.raises(ActivitySummarySettingsVersionConflict):
        await repository.save_summary_settings(changed, expected_version=0, now=now)

    async with database.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_settings WHERE singleton_id = 1"
            )
        ).fetchone()
    assert row is not None
    stored = json.loads(row["config"])
    assert "prompt" not in stored
    assert stored["prompt_version"] == ACTIVITY_SUMMARY_PROMPT_VERSION


async def test_analyzer_uses_fixed_chinese_prompt_and_all_three_connector_sources() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="event-1",
        timestamp=start,
        duration=3600,
        application="Code",
    )
    connectors = (
        ConnectorKind.GITHUB,
        ConnectorKind.GMAIL,
        ConnectorKind.GOOGLE_CALENDAR,
    )
    feed = ConnectorFeed(
        workspace_id="workspace-1",
        generated_at=start + timedelta(hours=2),
        sources=tuple(
            ConnectorFeedSource(
                connector=connector,
                label=connector.value,
                health=ConnectorFeedHealth.HEALTHY,
                connected=True,
                enabled=True,
                stale=False,
                item_count=1,
                snapshot_fetched_at=start + timedelta(hours=2),
                fetch_strategy=CONNECTOR_DEFINITIONS[connector].fetch_strategy,
                coverage_past_days=CONNECTOR_DEFINITIONS[connector].coverage_past_days,
                coverage_future_days=CONNECTOR_DEFINITIONS[connector].coverage_future_days,
            )
            for connector in connectors
        ),
        items=tuple(
            ConnectorFeedItem(
                connector=connector,
                source_id=f"source-{connector.value}",
                occurred_at=start + timedelta(hours=1),
                title=f"{connector.value} source title",
                summary=f"{connector.value} source summary",
            )
            for connector in connectors
        ),
    )

    class Adapter:
        request = None

        async def complete(self, request):
            self.request = request
            return FinalTurn(
                content=json.dumps(
                    {
                        "summary": (
                            "本阶段有一小时可验证的活跃记录；GitHub、Gmail 和 "
                            "Google Calendar 三类只读快照均提供了窗口内上下文。"
                        )
                    },
                    ensure_ascii=False,
                )
            )

    adapter = Adapter()

    async def resolve_route(_task):
        return ActivityAnalysisRoute(
            adapter=adapter,
            provider="minimax",
            model="MiniMax-M3",
            configuration_version=4,
            summary_settings_version=7,
            prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
            connector_feed=feed,
        )

    task, evidence = _task_and_evidence(start=start, fact=fact)
    analysis = await ActivitySummaryAnalyzer(resolve_route=resolve_route).analyze(
        task=task,
        evidence=evidence,
    )

    assert adapter.request is not None
    system_prompt = adapter.request.agent.system_prompt
    model_payload = adapter.request.messages[-1].content
    assert ACTIVITY_SUMMARY_SYSTEM_PROMPT in system_prompt
    assert "简体中文" in system_prompt
    assert "hypotheses" not in system_prompt
    assert set(reference.connector for reference in analysis.connector_evidence_refs) == {
        "github",
        "gmail",
        "google_calendar",
    }
    assert tuple(item.connector for item in analysis.connector_coverage) == (
        "github",
        "gmail",
        "google_calendar",
    )
    assert all(item.health == "healthy" for item in analysis.connector_coverage)
    assert all(item.window_item_count == 1 for item in analysis.connector_coverage)
    assert all(len(item.snapshot_watermark) == 64 for item in analysis.connector_coverage)
    assert all(f'"connector":"{connector.value}"' in model_payload for connector in connectors)
    assert "本阶段" in analysis.summary_text
    assert not hasattr(analysis, "inferences")


async def test_english_only_model_output_is_rejected_without_a_local_revision() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="event-1",
        timestamp=start,
        duration=3600,
        application="Code",
    )

    class Adapter:
        async def complete(self, _request):
            return FinalTurn(content='{"summary":"One hour of active work was observed."}')

    async def resolve_route(_task):
        return ActivityAnalysisRoute(
            adapter=Adapter(),
            provider="minimax",
            model="MiniMax-M3",
            prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
        )

    task, evidence = _task_and_evidence(start=start, fact=fact)
    with pytest.raises(ActivityModelOutputRejectedError):
        await ActivitySummaryAnalyzer(resolve_route=resolve_route).analyze(
            task=task,
            evidence=evidence,
        )


async def test_unavailable_configured_model_propagates_for_durable_retry() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="event-1",
        timestamp=start,
        duration=3600,
        application="Code",
    )

    class UnavailableAdapter:
        async def complete(self, _request):
            raise MiniMaxAuthenticationError("credential unavailable")

    async def resolve_route(_task):
        return ActivityAnalysisRoute(
            adapter=UnavailableAdapter(),
            provider="minimax",
            model="MiniMax-M3",
            configuration_version=4,
        )

    task, evidence = _task_and_evidence(start=start, fact=fact)
    with pytest.raises(MiniMaxAuthenticationError, match="credential unavailable"):
        await ActivitySummaryAnalyzer(resolve_route=resolve_route).analyze(
            task=task,
            evidence=evidence,
        )


async def test_local_fallback_counts_calendar_event_overlapping_window_start() -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="event-1",
        timestamp=start,
        duration=3_600,
        application="Code",
    )
    feed = ConnectorFeed(
        workspace_id="workspace-1",
        generated_at=start + timedelta(hours=2),
        sources=(
            ConnectorFeedSource(
                connector=ConnectorKind.GOOGLE_CALENDAR,
                label="Google Calendar",
                health=ConnectorFeedHealth.HEALTHY,
                connected=True,
                enabled=True,
                stale=False,
                item_count=1,
                snapshot_fetched_at=start + timedelta(hours=2),
                fetch_strategy=CONNECTOR_DEFINITIONS[ConnectorKind.GOOGLE_CALENDAR].fetch_strategy,
                coverage_past_days=CONNECTOR_DEFINITIONS[
                    ConnectorKind.GOOGLE_CALENDAR
                ].coverage_past_days,
                coverage_future_days=CONNECTOR_DEFINITIONS[
                    ConnectorKind.GOOGLE_CALENDAR
                ].coverage_future_days,
            ),
        ),
        items=(
            ConnectorFeedItem(
                connector=ConnectorKind.GOOGLE_CALENDAR,
                source_id="calendar-cross-boundary",
                occurred_at=start - timedelta(hours=1),
                ends_at=start + timedelta(minutes=30),
                title="Cross-boundary calendar event",
                summary="Calendar metadata",
            ),
        ),
    )

    async def resolve_route(_task):
        return ActivityAnalysisRoute(
            adapter=None,
            provider="minimax",
            model="MiniMax-M3",
            connector_feed=feed,
        )

    task, evidence = _task_and_evidence(start=start, fact=fact)
    analysis = await ActivitySummaryAnalyzer(resolve_route=resolve_route).analyze(
        task=task,
        evidence=evidence,
    )

    assert "Google Calendar 1 条" in analysis.summary_text
    calendar_coverage = next(
        item for item in analysis.connector_coverage if item.connector == "google_calendar"
    )
    assert calendar_coverage.window_item_count == 1


async def test_summary_revision_persists_connector_evidence_refs(tmp_path: Path) -> None:
    start = datetime(2026, 7, 18, 0, tzinfo=UTC)
    fact = ObservedActivityFact(
        kind="window",
        bucket_id="window",
        event_id="event-1",
        timestamp=start,
        duration=3600,
        application="Code",
    )
    task, evidence = _task_and_evidence(start=start, fact=fact)
    feed = ConnectorFeed(
        workspace_id="workspace-1",
        generated_at=start + timedelta(hours=2),
        sources=(
            ConnectorFeedSource(
                connector=ConnectorKind.GITHUB,
                label="GitHub",
                health=ConnectorFeedHealth.HEALTHY,
                connected=True,
                enabled=True,
                stale=False,
                item_count=1,
                snapshot_fetched_at=start + timedelta(hours=2),
                fetch_strategy=CONNECTOR_DEFINITIONS[ConnectorKind.GITHUB].fetch_strategy,
                coverage_past_days=CONNECTOR_DEFINITIONS[ConnectorKind.GITHUB].coverage_past_days,
                coverage_future_days=CONNECTOR_DEFINITIONS[
                    ConnectorKind.GITHUB
                ].coverage_future_days,
            ),
        ),
        items=(
            ConnectorFeedItem(
                connector=ConnectorKind.GITHUB,
                source_id="github-1",
                occurred_at=start + timedelta(hours=1),
                title="Pull request",
                summary="Updated code",
            ),
        ),
    )

    async def resolve_route(_task):
        return ActivityAnalysisRoute(
            adapter=None,
            provider="local",
            model="deterministic-activity-v1",
            prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
            connector_feed=feed,
        )

    database = Database(tmp_path / "ledger.db")
    await database.initialize()
    repository = ActivityRepository(database)
    rules = evidence.category_rules
    await repository.save_category_rule_version(rules, now=task.updated_at)
    await repository.save_source_state(
        ActivitySourceState(
            health=ActivitySourceHealth.AVAILABLE,
            checked_at=task.updated_at,
            server_id="device",
            category_rule_version=rules.id,
        )
    )
    await repository.ensure_tasks([task])

    class Semantic:
        async def collect_window(self, **_arguments):
            return evidence

    completed = await ActivitySummaryService(
        repository=repository,
        semantic=Semantic(),
        analyzer=ActivitySummaryAnalyzer(resolve_route=resolve_route),
    ).execute_task(task.id, now=task.updated_at)
    revision = await repository.latest_revision(task.id)

    assert completed.status.value == "completed"
    assert revision is not None
    assert revision.prompt_version == ACTIVITY_SUMMARY_PROMPT_VERSION
    assert revision.fallback_reason == "activity_model_route_unavailable"
    assert revision.requested_provider == "local"
    assert revision.requested_model == "deterministic-activity-v1"
    attempts = await repository.list_attempts(task.id)
    assert attempts[-1].fallback_reason == "activity_model_route_unavailable"
    assert attempts[-1].requested_provider == "local"
    assert attempts[-1].requested_model == "deterministic-activity-v1"
    assert len(revision.connector_evidence_refs) == 1
    assert revision.connector_evidence_refs[0].connector == "github"
    coverage = {item.connector: item for item in revision.connector_coverage}
    assert tuple(coverage) == ("github", "gmail", "google_calendar")
    assert coverage["github"].health == "healthy"
    assert coverage["github"].window_item_count == 1
    assert coverage["gmail"].health == "unavailable"
    assert coverage["gmail"].window_item_count == 0
    assert coverage["google_calendar"].health == "unavailable"
    assert coverage["google_calendar"].window_item_count == 0
    async with database.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT config FROM activity_summary_revisions WHERE id = ?",
                (revision.id,),
            )
        ).fetchone()
    assert row is not None
    stored = json.loads(row["config"])
    assert stored["fallback_reason"] == "activity_model_route_unavailable"
    assert stored["requested_provider"] == "local"
    assert stored["requested_model"] == "deterministic-activity-v1"
    assert [item["connector"] for item in stored["connector_coverage"]] == [
        "github",
        "gmail",
        "google_calendar",
    ]
    serialized_coverage = json.dumps(stored["connector_coverage"], sort_keys=True)
    assert "github-1" not in serialized_coverage
    assert "Pull request" not in serialized_coverage
    assert "Updated code" not in serialized_coverage


def _task_and_evidence(
    *,
    start: datetime,
    fact: ObservedActivityFact,
):
    task = ActivityWindowPlanner().window(
        SummaryTaskType.STAGE_6H,
        window_start=start,
        window_end=start + timedelta(hours=6),
        created_at=start + timedelta(hours=7),
    )
    rules = category_rule_version([])
    evidence = ActivityWindowEvidence(
        statistics=ActivityStatistics(
            window_start=task.window_start,
            window_end=task.window_end,
            active_seconds=3600,
            application_seconds={"Code": 3600},
            observed_seconds=21600,
            window_observed_seconds=21600,
            afk_observed_seconds=21600,
            coverage_ratio=1,
            coverage_status=ActivityCoverageStatus.COMPLETE,
            source_watermark="w" * 64,
        ),
        evidence_refs=(
            fact.evidence_ref(
                server_id="device",
                fields_used=("kind", "timestamp", "duration", "application"),
            ),
        ),
        model_facts=(fact,),
        category_rules=rules,
    )
    return task, evidence
