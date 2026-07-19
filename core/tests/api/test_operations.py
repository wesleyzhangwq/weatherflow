from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.activity import (
    ActivitySourceHealth,
    ActivitySourceState,
    ActivitySummaryTask,
    ActivityWatchDiscovery,
    ActivityWatchInfo,
    CategoryRuleVersion,
    SummaryTaskType,
)
from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


class ResetActivityWatchClient:
    def __init__(self, *, now: datetime) -> None:
        self.now = now

    async def discover(self) -> ActivityWatchDiscovery:
        return ActivityWatchDiscovery(
            info=ActivityWatchInfo(
                hostname="macbook",
                version="0.13.2",
                device_id="device-1",
            ),
            buckets=(),
            data_start=self.now - timedelta(days=1),
            data_end=self.now,
            settings={},
            category_rules=CategoryRuleVersion(
                id="a" * 64,
                canonical_json="[]",
                rule_count=0,
            ),
        )

    async def close(self) -> None:
        return None


async def test_status_metrics_export_and_reset_require_explicit_requests(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    container = await RuntimeContainer.create(settings)
    transport = ASGITransport(app=create_app(settings, container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        onboarding_before = await client.get("/v1/onboarding")
        onboarding_complete = await client.post(
            "/v1/onboarding/complete",
            json={"confirm_local_ownership": True},
        )
        status = await client.get("/v1/system/status")
        metrics = await client.get("/v1/diagnostics/metrics")
        export = await client.post("/v1/diagnostics/export")
        preview = await client.get("/v1/privacy/reset/behavior")
        rejected = await client.post("/v1/privacy/reset/behavior", json={"confirm": False})
        accepted = await client.post("/v1/privacy/reset/behavior", json={"confirm": True})

    assert onboarding_before.json()["completed"] is False
    assert onboarding_complete.json()["completed"] is True
    assert "metadata_sensor_enabled" not in onboarding_complete.json()
    assert status.status_code == 200
    assert status.json()["onboarding_completed"] is True
    assert status.json()["local_only"] is True
    assert status.json()["telemetry_upload"] is False
    assert status.json()["behavior_sensor"]["raw_content_captured"] is False
    assert status.json()["model"] == {
        "configured": False,
        "provider": "echo",
        "model": None,
        "base_url": None,
        "credential_available": False,
    }
    assert metrics.status_code == 200
    assert export.status_code == 201
    assert Path(export.json()["path"]).is_relative_to(
        Path(container.default_workspace.internal_root)
    )
    assert preview.json()["category"] == "behavior"
    assert rejected.status_code == 409
    assert accepted.status_code == 200


async def test_activity_history_reset_is_explicit_and_installation_scoped(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    now = datetime.now(UTC)
    container = await RuntimeContainer.create(
        settings,
        activity_client=ResetActivityWatchClient(now=now),
    )
    category = CategoryRuleVersion(
        id="a" * 64,
        canonical_json="[]",
        rule_count=0,
    )
    await container.activity_repository.save_category_rule_version(category, now=now)
    await container.activity_repository.save_source_state(
        ActivitySourceState(
            health=ActivitySourceHealth.AVAILABLE,
            checked_at=now,
            category_rule_version=category.id,
        )
    )
    await container.activity_repository.ensure_tasks(
        [
            ActivitySummaryTask(
                id="activity-task",
                task_type=SummaryTaskType.STAGE_6H,
                window_start=now - timedelta(hours=6),
                window_end=now,
                not_before=now + timedelta(minutes=15),
                created_at=now,
                updated_at=now,
            )
        ]
    )
    expected_count = await container.activity_repository.history_count()
    transport = ASGITransport(app=create_app(settings, container=container))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        behavior = await client.post(
            "/v1/privacy/reset/behavior",
            json={"confirm": True},
        )
        retained = await container.activity_repository.history_count()
        preview = await client.get("/v1/privacy/reset/activity")
        rejected = await client.post(
            "/v1/privacy/reset/activity",
            json={"confirm": False},
        )
        reset = await client.post(
            "/v1/privacy/reset/activity",
            json={"confirm": True},
        )

    assert behavior.status_code == 200
    assert retained == expected_count
    assert preview.json() == {"category": "activity", "count": expected_count}
    assert rejected.status_code == 409
    assert reset.json() == {
        "category": "activity",
        "deleted_count": expected_count,
    }
    assert await container.activity_repository.history_count() == 0
    await container.activity_recovery.prepare(now=now + timedelta(minutes=1))
    assert await container.activity_repository.task_ids() == set()


async def test_security_scan_endpoint_reports_only_metadata(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    container = await RuntimeContainer.create(settings)
    transport = ASGITransport(app=create_app(settings, container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/security/scan")

    assert response.status_code == 200
    assert response.json() == {"findings": []}
