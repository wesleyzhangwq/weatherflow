import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.events import Actor, Event, RetentionClass, Sensitivity
from weatherflow.operations import ResetCategory, SecurityScanner
from weatherflow.rhythm import CheckInSignal


async def test_diagnostic_export_is_explicit_local_bounded_and_redacted(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = container.default_workspace
    await container.ledger.append(
        Event.new(
            type="provider.failed",
            actor=Actor.SYSTEM,
            stream_kind="workspace",
            stream_id=workspace.id,
            correlation_id=workspace.id,
            payload={"authorization": "Bearer do-not-export", "provider": "calendar"},
            sensitivity=Sensitivity.PRIVATE,
        )
    )
    run, _ = await container.submit_run(
        user_intent="diagnose local harness",
        client_request_id="diagnostic-run",
    )

    metrics = await container.diagnostics.metrics(workspace.id)
    exported = await container.diagnostics.export(workspace.id)

    assert metrics.run_counts["succeeded"] == 1
    assert exported.path.is_relative_to(Path(workspace.internal_root))
    assert exported.path.name == "diagnostic.json"
    payload = exported.path.read_text()
    assert "do-not-export" not in payload
    assert "Bearer" not in payload
    parsed = json.loads(payload)
    assert parsed["schema_version"] == "1"
    assert parsed["upload_attempted"] is False
    assert parsed["metrics"]["run_counts"]["succeeded"] == 1
    timeline = await container.ledger.list_correlation(workspace.id, limit=1000)
    assert any(event.type == "diagnostics.exported" for event in timeline)
    assert run.id not in payload or len(payload) < 100_000


async def test_resets_are_independent_and_audit_contains_counts_not_content(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = container.default_workspace
    current = await container.rhythm.ingest(
        workspace.id,
        CheckInSignal(text="very private overload detail", observed_at=datetime.now(UTC)),
    )
    source_id = current.snapshot.supporting_event_ids[0]
    await container.memory.remember_episode(
        workspace_id=workspace.id,
        summary="private memory body",
        source_event_ids=(source_id,),
    )

    behavior_preview = await container.privacy.preview_reset(workspace.id, ResetCategory.BEHAVIOR)
    behavior_result = await container.privacy.reset(workspace.id, ResetCategory.BEHAVIOR)

    assert behavior_preview.count >= 1
    assert behavior_result.deleted_count == behavior_preview.count
    assert len(await container.memory.episodes.list_workspace(workspace.id)) == 1

    memory_result = await container.privacy.reset(workspace.id, ResetCategory.MEMORY)
    assert memory_result.deleted_count == 1
    assert await container.memory.episodes.list_workspace(workspace.id) == []
    events = await container.ledger.list_stream("workspace", workspace.id, limit=1000)
    audit_payload = "".join(
        json.dumps(event.payload) for event in events if event.type == "privacy.reset_completed"
    )
    assert "very private overload detail" not in audit_payload
    assert "private memory body" not in audit_payload


async def test_retention_expires_only_eligible_behavior_events(tmp_path: Path) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = container.default_workspace
    old = Event.new(
        type="rhythm.signal.activity_metadata",
        actor=Actor.SYSTEM,
        stream_kind="workspace",
        stream_id=workspace.id,
        correlation_id=workspace.id,
        payload={"signal": {"kind": "activity_metadata"}},
        retention_class=RetentionClass.SIGNAL_RAW,
    ).model_copy(update={"recorded_at": datetime.now(UTC) - timedelta(days=4)})
    audit = Event.new(
        type="approval.decided",
        actor=Actor.USER,
        stream_kind="workspace",
        stream_id=workspace.id,
        correlation_id=workspace.id,
        payload={},
        retention_class=RetentionClass.AUDIT,
    ).model_copy(update={"recorded_at": datetime.now(UTC) - timedelta(days=400)})
    await container.ledger.append(old)
    await container.ledger.append(audit)

    result = await container.privacy.expire(workspace.id)

    assert result.deleted_count == 1
    assert await container.ledger.get(old.id) is None
    assert await container.ledger.get(audit.id) is not None


async def test_security_scan_detects_raw_sensor_content_and_secret_values(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    clean = await SecurityScanner(container.database).scan()
    assert clean.findings == ()
    async with container.database.transaction() as connection:
        await connection.execute(
            "UPDATE checkpoints SET state = ? WHERE run_id = ?",
            ('{"clipboard":"raw content","token":"sk-secret-value"}', "missing"),
        )
        await connection.execute(
            """
            INSERT INTO events(
                id, type, recorded_at, actor, stream_kind, stream_id,
                correlation_id, causation_id, payload, sensitivity, retention_class
            ) VALUES ('leak', 'test.leak', ?, 'system', 'workspace', ?, ?, NULL,
                      '{"clipboard":"raw content","token":"sk-secret-value"}',
                      'normal', 'audit')
            """,
            (
                datetime.now(UTC).isoformat(),
                container.default_workspace.id,
                container.default_workspace.id,
            ),
        )

    scan = await SecurityScanner(container.database).scan()

    assert {finding.kind for finding in scan.findings} == {
        "forbidden_sensor_field",
        "secret_value",
    }
    assert all("raw content" not in finding.model_dump_json() for finding in scan.findings)
