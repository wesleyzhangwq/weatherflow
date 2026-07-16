import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from weatherflow.activity import (
    ActivityHeartbeat,
    ActivityInferenceJobStatus,
    ActivityInferenceRepository,
    ActivityInferenceRoute,
    ActivityInferenceSchedule,
    ActivityInferenceService,
    ActivityPreferences,
    ActivityRepository,
    ActivityService,
)
from weatherflow.rhythm import DimensionName, HumanStateSnapshot
from weatherflow.runtime import FinalTurn, ModelRequest
from weatherflow.storage import Database

SHANGHAI = ZoneInfo("Asia/Shanghai")


def local_time(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SHANGHAI).astimezone(UTC)


def test_inference_schedule_uses_beijing_06_through_prior_day_24() -> None:
    schedule = ActivityInferenceSchedule()

    assert schedule.due_slot(local_time(2026, 7, 16, 5, 59)) is None
    assert schedule.due_slot(local_time(2026, 7, 16, 6, 0)) == local_time(2026, 7, 16, 6)
    assert schedule.due_slot(local_time(2026, 7, 16, 23, 47)) == local_time(2026, 7, 16, 23)
    assert schedule.due_slot(local_time(2026, 7, 17, 0, 30)) == local_time(2026, 7, 17, 0)
    assert schedule.due_slot(local_time(2026, 7, 17, 1, 0)) is None
    assert schedule.due_slot(local_time(2026, 7, 17, 5, 59)) is None


def test_inference_schedule_previous_slot_crosses_quiet_window() -> None:
    schedule = ActivityInferenceSchedule()

    assert schedule.previous_slot(local_time(2026, 7, 17, 6)) == local_time(2026, 7, 17, 0)
    assert schedule.previous_slot(local_time(2026, 7, 17, 0)) == local_time(2026, 7, 16, 23)
    assert schedule.previous_slot(local_time(2026, 7, 16, 12)) == local_time(2026, 7, 16, 11)


async def test_inference_job_claim_is_idempotent_and_recovery_needs_review(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    repository = ActivityInferenceRepository(database)
    scheduled_for = local_time(2026, 7, 16, 8)
    now = scheduled_for + timedelta(minutes=5)

    first = await repository.claim(
        scheduled_for=scheduled_for,
        window_start=local_time(2026, 7, 16, 7),
        workspace_id="workspace-1",
        now=now,
    )
    duplicate = await repository.claim(
        scheduled_for=scheduled_for,
        window_start=local_time(2026, 7, 16, 7),
        workspace_id="workspace-1",
        now=now + timedelta(seconds=1),
    )
    executing = await repository.mark_executing(
        first.id,
        provider="openai",
        model="gpt-test",
        event_ids=("event-1",),
        redaction_count=2,
        request_payload="<untrusted_activity_data>[]</untrusted_activity_data>",
        now=now,
    )
    recovered = await repository.recover_executing(now=now + timedelta(minutes=1))

    assert duplicate.id == first.id
    assert executing.status is ActivityInferenceJobStatus.EXECUTING
    assert recovered[0].status is ActivityInferenceJobStatus.NEEDS_REVIEW
    assert recovered[0].error_code == "delivery_uncertain_after_restart"


class StructuredStateModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> FinalTurn:
        self.requests.append(request)
        event_ids = re.findall(r'"id":\s*"([^"]+)"', request.messages[-1].content)
        evidence = event_ids[-1:]
        dimensions: dict[str, Any] = {
            name.value: {
                "value": 0.6,
                "confidence": 0.8,
                "trend": "steady",
                "evidence_event_ids": evidence,
            }
            for name in DimensionName
        }
        return FinalTurn(
            content=json.dumps(
                {
                    "dimensions": dimensions,
                    "summary": "Sustained focus with manageable recovery need.",
                    "evidence_event_ids": evidence,
                }
            )
        )


def window_heartbeat(*, event_id: str, observed_at: datetime) -> ActivityHeartbeat:
    return ActivityHeartbeat(
        source="macos_window",
        device_id="macbook",
        source_instance="native-main",
        source_event_id=event_id,
        observed_at=observed_at,
        pulsetime_seconds=600,
        app_name="Visual Studio Code",
        bundle_id="com.microsoft.VSCode",
        window_title="WeatherFlow",
        focused=True,
        idle_state="active",
        category="development",
    )


async def test_inference_service_coalesces_missed_hours_and_audits_remote_payload(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    activity_repository = ActivityRepository(database)
    activity = ActivityService(repository=activity_repository)
    await activity.update_preferences(
        ActivityPreferences(
            collection_enabled=True,
            macos_enabled=True,
            remote_inference_enabled=True,
            model_workspace_id="workspace-1",
        ),
        expected_version=0,
    )
    await activity.ingest(
        window_heartbeat(event_id="window-1", observed_at=local_time(2026, 7, 16, 6, 30))
    )
    await activity.ingest(
        window_heartbeat(event_id="window-2", observed_at=local_time(2026, 7, 16, 6, 40))
    )

    model = StructuredStateModel()
    published: list[HumanStateSnapshot] = []

    async def resolve_route(_workspace_id: str) -> ActivityInferenceRoute:
        return ActivityInferenceRoute(
            adapter=model,
            provider="openai",
            model="gpt-test",
            base_url="https://api.openai.com/v1",
            configuration_version=3,
        )

    async def publish(snapshot: HumanStateSnapshot) -> None:
        published.append(snapshot)

    repository = ActivityInferenceRepository(database)
    service = ActivityInferenceService(
        activity=activity,
        repository=repository,
        resolve_route=resolve_route,
        publish_snapshot=publish,
    )
    first = await service.tick(now=local_time(2026, 7, 16, 7, 5))
    await activity.ingest(
        window_heartbeat(event_id="window-3", observed_at=local_time(2026, 7, 16, 8, 30))
    )
    await activity.ingest(
        window_heartbeat(event_id="window-4", observed_at=local_time(2026, 7, 16, 8, 40))
    )
    coalesced = await service.tick(now=local_time(2026, 7, 16, 10, 20))
    duplicate = await service.tick(now=local_time(2026, 7, 16, 10, 45))

    assert first is not None and first.status is ActivityInferenceJobStatus.COMPLETED
    assert coalesced is not None
    assert coalesced.status is ActivityInferenceJobStatus.COMPLETED
    assert coalesced.scheduled_for == local_time(2026, 7, 16, 10)
    assert coalesced.window_start == local_time(2026, 7, 16, 7)
    assert duplicate is not None and duplicate.id == coalesced.id
    assert len(model.requests) == 2
    assert model.requests[-1].tools == ()
    assert "<untrusted_activity_data>" in coalesced.request_payload
    assert coalesced.provider == "openai"
    assert coalesced.model == "gpt-test"
    assert coalesced.base_url == "https://api.openai.com/v1"
    assert coalesced.configuration_version == 3
    assert coalesced.event_count == 1
    assert len(published) == 2
    assert set(published[-1].dimensions) == set(DimensionName)


async def test_inference_chunks_complete_event_set_and_fuses_without_tools(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    activity_repository = ActivityRepository(database)
    activity = ActivityService(repository=activity_repository)
    await activity.update_preferences(
        ActivityPreferences(
            collection_enabled=True,
            macos_enabled=True,
            remote_inference_enabled=True,
            model_workspace_id="workspace-1",
        ),
        expected_version=0,
    )
    started = local_time(2026, 7, 16, 6, 0)
    for index in range(501):
        heartbeat = window_heartbeat(
            event_id=f"window-{index}",
            observed_at=started + timedelta(seconds=index),
        ).model_copy(
            update={
                "app_name": f"Application {index}",
                "bundle_id": f"app.weatherflow.{index}",
            }
        )
        await activity.ingest(heartbeat)

    model = StructuredStateModel()
    published: list[HumanStateSnapshot] = []

    async def resolve_route(_workspace_id: str) -> ActivityInferenceRoute:
        return ActivityInferenceRoute(
            adapter=model,
            provider="openai",
            model="gpt-test",
        )

    async def publish(snapshot: HumanStateSnapshot) -> None:
        published.append(snapshot)

    service = ActivityInferenceService(
        activity=activity,
        repository=ActivityInferenceRepository(database),
        resolve_route=resolve_route,
        publish_snapshot=publish,
    )
    job = await service.tick(now=local_time(2026, 7, 16, 7, 5))

    assert job is not None and job.status is ActivityInferenceJobStatus.COMPLETED
    assert job.event_count == 501
    assert job.chunk_count >= 2
    assert len(model.requests) == job.chunk_count + 1
    assert all(request.tools == () for request in model.requests)
    assert all(
        len(request.messages[-1].content.encode()) <= 128 * 1024 for request in model.requests
    )
    assert len(published) == 1


async def test_concurrent_scheduler_ticks_deliver_one_remote_request(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    activity = ActivityService(repository=ActivityRepository(database))
    await activity.update_preferences(
        ActivityPreferences(
            collection_enabled=True,
            macos_enabled=True,
            remote_inference_enabled=True,
            model_workspace_id="workspace-1",
        ),
        expected_version=0,
    )
    await activity.ingest(
        window_heartbeat(
            event_id="window-1",
            observed_at=local_time(2026, 7, 16, 6, 30),
        )
    )
    model = StructuredStateModel()

    async def resolve_route(_workspace_id: str) -> ActivityInferenceRoute:
        await asyncio.sleep(0)
        return ActivityInferenceRoute(adapter=model, provider="openai", model="gpt-test")

    async def publish(_snapshot: HumanStateSnapshot) -> None:
        return None

    service = ActivityInferenceService(
        activity=activity,
        repository=ActivityInferenceRepository(database),
        resolve_route=resolve_route,
        publish_snapshot=publish,
    )
    first, second = await asyncio.gather(
        service.tick(now=local_time(2026, 7, 16, 7, 5)),
        service.tick(now=local_time(2026, 7, 16, 7, 5)),
    )

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(model.requests) == 1
