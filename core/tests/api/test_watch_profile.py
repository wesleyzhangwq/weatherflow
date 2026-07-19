from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from weatherflow.api.app import create_app
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.memory import ProfileAssertionStatus


async def test_watch_profile_lists_only_active_evidence_backed_assertions(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace_id = container.default_workspace.id
    await container.rhythm.record_task_behavior(
        workspace_id=workspace_id,
        run_id="run-profile-evidence",
        outcome="succeeded",
        observed_at=datetime.now(UTC),
        duration_seconds=120,
        step_count=2,
    )
    events = await container.ledger.list_stream("workspace", workspace_id, limit=1000)
    evidence = next(event for event in events if event.type == "rhythm.signal.task_behavior")
    active = await container.memory.create_assertion(
        workspace_id=workspace_id,
        claim="长任务之后更适合留出短暂恢复时间。",
        confidence=0.82,
        evidence_event_ids=(evidence.id,),
        origin="derived",
    )
    retracted = await container.memory.create_assertion(
        workspace_id=workspace_id,
        claim="这条旧画像不应继续展示。",
        confidence=0.4,
        evidence_event_ids=(evidence.id,),
        origin="agent",
    )
    await container.memory.update_assertion(
        retracted.id,
        expected_version=retracted.version,
        status=ProfileAssertionStatus.RETRACTED,
    )

    transport = ASGITransport(app=create_app(container=container))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/watch/profile",
            params={"workspace_id": workspace_id},
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": active.id,
            "claim": active.claim,
            "confidence": active.confidence,
            "origin": active.origin,
            "evidence_count": 1,
            "updated_at": active.updated_at.isoformat().replace("+00:00", "Z"),
        }
    ]
