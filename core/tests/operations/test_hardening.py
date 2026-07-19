import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.events import Actor, Event, RetentionClass, Sensitivity
from weatherflow.operations import ResetCategory, SecurityScanner
from weatherflow.rhythm import CheckInSignal
from weatherflow.runs import RunStatus
from weatherflow.runtime import AgentMessage, MessageRole


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

    assert metrics.run_counts["waiting_user"] == 1
    assert exported.path.is_relative_to(Path(workspace.internal_root))
    assert exported.path.name == "diagnostic.json"
    payload = exported.path.read_text()
    assert "do-not-export" not in payload
    assert "Bearer" not in payload
    parsed = json.loads(payload)
    assert parsed["schema_version"] == "1"
    assert parsed["upload_attempted"] is False
    assert parsed["metrics"]["run_counts"]["waiting_user"] == 1
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
    memory_preset = container.mcp_management.catalog.require("memory")
    mcp_memory_file = memory_preset.state_root(Path(workspace.internal_root)) / "memory.jsonl"
    mcp_memory_file.parent.mkdir(parents=True)
    mcp_memory_file.write_text('{"type":"entity"}\n{"type":"relation"}\n')

    behavior_preview = await container.privacy.preview_reset(workspace.id, ResetCategory.BEHAVIOR)
    behavior_result = await container.privacy.reset(workspace.id, ResetCategory.BEHAVIOR)

    assert behavior_preview.count >= 1
    assert behavior_result.deleted_count == behavior_preview.count
    assert len(await container.memory.episodes.list_workspace(workspace.id)) == 1

    memory_preview = await container.privacy.preview_reset(workspace.id, ResetCategory.MEMORY)
    memory_result = await container.privacy.reset(workspace.id, ResetCategory.MEMORY)
    assert memory_preview.count == 3
    assert memory_result.deleted_count == memory_preview.count
    assert await container.memory.episodes.list_workspace(workspace.id) == []
    assert not mcp_memory_file.exists()
    events = await container.ledger.list_stream("workspace", workspace.id, limit=1000)
    audit_payload = "".join(
        json.dumps(event.payload) for event in events if event.type == "privacy.reset_completed"
    )
    assert "very private overload detail" not in audit_payload
    assert "private memory body" not in audit_payload


async def test_activity_reset_scrubs_activity_tainted_run_content_only(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    workspace = container.default_workspace
    activity_run, _ = await container.submit_run(
        user_intent="Inspect my recent activity",
        client_request_id="activity-reset-tainted-run",
        execute=False,
    )
    ordinary_run, _ = await container.submit_run(
        user_intent="Read the project README",
        client_request_id="activity-reset-ordinary-run",
        execute=False,
    )
    activity_checkpoint = await container.checkpoints.get(activity_run.id)
    ordinary_checkpoint = await container.checkpoints.get(ordinary_run.id)
    assert activity_checkpoint is not None
    assert ordinary_checkpoint is not None
    activity_sentinel = "ACTIVITY_DERIVED_RUN_SENTINEL"
    activity_result_event = Event.new(
        type="run.result_committed",
        actor=Actor.AGENT,
        stream_kind="run",
        stream_id=activity_run.id,
        correlation_id=activity_run.id,
        payload={"summary": activity_sentinel},
    )
    ordinary_result_event = Event.new(
        type="run.result_committed",
        actor=Actor.AGENT,
        stream_kind="run",
        stream_id=ordinary_run.id,
        correlation_id=ordinary_run.id,
        payload={"summary": "ordinary durable result"},
    )
    tainted_transcript = (
        AgentMessage(role=MessageRole.USER, content="keep original user request"),
        AgentMessage(
            role=MessageRole.ASSISTANT,
            content=('{"kind":"tool_call","tool_id":"activity.current_state","arguments":{}}'),
        ),
        AgentMessage(
            role=MessageRole.TOOL,
            name="activity.current_state",
            content=f'{{"summary":"{activity_sentinel}"}}',
        ),
        AgentMessage(
            role=MessageRole.ASSISTANT,
            content=f"Derived answer: {activity_sentinel}",
        ),
        AgentMessage(role=MessageRole.USER, content="keep unrelated follow-up"),
        AgentMessage(
            role=MessageRole.ASSISTANT,
            content="ordinary answer after the new user message",
        ),
    )
    ordinary_transcript = (
        AgentMessage(role=MessageRole.USER, content="keep ordinary user request"),
        AgentMessage(
            role=MessageRole.TOOL,
            name="files.read",
            content='{"path":"README.md"}',
        ),
        AgentMessage(role=MessageRole.ASSISTANT, content="ordinary durable result"),
    )
    async with container.database.transaction() as connection:
        await container.checkpoints.save_in(
            connection,
            activity_checkpoint.model_copy(update={"transcript": tainted_transcript}),
            expected_version=activity_checkpoint.version,
        )
        await container.checkpoints.save_in(
            connection,
            ordinary_checkpoint.model_copy(update={"transcript": ordinary_transcript}),
            expected_version=ordinary_checkpoint.version,
        )
        await connection.execute(
            "UPDATE runs SET result_summary = ? WHERE id = ?",
            (activity_sentinel, activity_run.id),
        )
        await connection.execute(
            "UPDATE runs SET result_summary = ? WHERE id = ?",
            ("ordinary durable result", ordinary_run.id),
        )
        await container.ledger.append_in(connection, activity_result_event)
        await container.ledger.append_in(connection, ordinary_result_event)

    derived_history_count = await container.activity_repository.history_count()
    preview = await container.privacy.preview_reset(workspace.id, ResetCategory.ACTIVITY)

    assert preview.count == derived_history_count + 3

    result = await container.privacy.reset(workspace.id, ResetCategory.ACTIVITY)

    assert result.deleted_count == preview.count
    scrubbed_checkpoint = await container.checkpoints.get(activity_run.id)
    retained_checkpoint = await container.checkpoints.get(ordinary_run.id)
    scrubbed_run = await container.runs.get(activity_run.id)
    retained_run = await container.runs.get(ordinary_run.id)
    assert scrubbed_checkpoint is not None
    assert retained_checkpoint is not None
    assert scrubbed_run is not None
    assert retained_run is not None
    assert [message.content for message in scrubbed_checkpoint.transcript] == [
        "keep original user request",
        "keep unrelated follow-up",
        "ordinary answer after the new user message",
    ]
    assert activity_sentinel not in scrubbed_checkpoint.model_dump_json()
    assert scrubbed_run.result_summary is None
    assert await container.ledger.get(activity_result_event.id) is None
    assert retained_checkpoint.transcript == ordinary_transcript
    assert retained_run.result_summary == "ordinary durable result"
    retained_event = await container.ledger.get(ordinary_result_event.id)
    assert retained_event is not None
    assert retained_event.payload == {"summary": "ordinary durable result"}
    physical_bytes = container.database.path.read_bytes()
    wal_path = container.database.path.with_name(f"{container.database.path.name}-wal")
    if wal_path.exists():
        physical_bytes += wal_path.read_bytes()
    assert activity_sentinel.encode() not in physical_bytes


async def test_activity_reset_cancels_pending_activity_run_and_clears_replay_state(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    run, _ = await container.submit_run(
        user_intent="Check my current activity",
        client_request_id="activity-reset-pending-run",
        execute=False,
    )
    checkpoint = await container.checkpoints.get(run.id)
    assert checkpoint is not None
    pending_turn = {
        "kind": "tool_call",
        "call_id": "pending-activity-call",
        "tool_id": "activity.current_state",
        "arguments": {},
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": None},
    }
    pending = checkpoint.model_copy(
        update={
            "transcript": (
                *checkpoint.transcript,
                AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=json.dumps(pending_turn),
                ),
            ),
            "state": {
                **checkpoint.state,
                "pending_turn": pending_turn,
                "tool_free_next_turn": True,
            },
        }
    )
    async with container.database.transaction() as connection:
        await container.checkpoints.save_in(
            connection,
            pending,
            expected_version=checkpoint.version,
        )

    preview = await container.privacy.preview_reset(
        container.default_workspace.id,
        ResetCategory.ACTIVITY,
    )
    result = await container.privacy.reset(
        container.default_workspace.id,
        ResetCategory.ACTIVITY,
    )

    assert result.deleted_count == preview.count
    cancelled = await container.runs.get(run.id)
    scrubbed = await container.checkpoints.get(run.id)
    assert cancelled is not None and cancelled.status is RunStatus.CANCELLED
    assert scrubbed is not None
    assert all("activity.current_state" not in message.content for message in scrubbed.transcript)
    assert "pending_turn" not in scrubbed.state
    assert "tool_free_next_turn" not in scrubbed.state
    assert scrubbed.state["activity_history_reset"] is True


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
    async with container.database.connect() as connection:
        rows = await (
            await connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).fetchall()
        table_names = {str(row["name"]) for row in rows}
        evidence_schema = await (
            await connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'activity_evidence_refs'"
            )
        ).fetchone()

    assert {
        "activity_state_inferences",
        "activity_live_inferences",
        "activity_live_evidence_refs",
        "activity_live_state_assessments",
    }.isdisjoint(table_names)
    assert evidence_schema is not None
    assert "owner_type TEXT NOT NULL CHECK(owner_type = 'revision')" in evidence_schema["sql"]
    run, _ = await container.submit_run(
        user_intent="scan durable run fields",
        client_request_id="security-scan-run",
        execute=False,
    )
    provider_token = "ghp_" + "sensitivevalue12345"
    artifact = await container.artifact_store.put_bytes(
        run_id=run.id,
        workspace=container.default_workspace,
        name="unsafe-provider-output.txt",
        media_type="text/plain",
        data=f"provider output contained {provider_token}".encode(),
    )
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
        await connection.execute(
            "UPDATE runs SET result_summary = ? WHERE id = ?",
            (f"provider returned {provider_token}", run.id),
        )
        await connection.execute(
            """
            INSERT INTO connector_snapshots(workspace_id, connector, fetched_at, snapshot)
            VALUES (?, 'gmail', ?, ?)
            """,
            (
                container.default_workspace.id,
                datetime.now(UTC).isoformat(),
                json.dumps({"summary": f"api_key={provider_token}"}),
            ),
        )
        now = datetime.now(UTC).isoformat()
        await connection.execute(
            """
            INSERT INTO activity_category_rule_versions(
                id, canonical_json, rule_count, created_at
            ) VALUES (?, '[]', 0, ?)
            """,
            ("c" * 64, now),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_tasks(
                id, task_type, window_start, window_end, timezone,
                boundary_policy_version, status, finality, attempt_count,
                not_before, current_revision, config, created_at, updated_at
            ) VALUES (
                'activity-security-task', 'stage_6h', ?, ?, 'Asia/Shanghai',
                'activity-window-boundaries-v1', 'completed', 'final', 1,
                ?, 1, '{}', ?, ?
            )
            """,
            ("2026-07-16T00:00:00+00:00", now, now, now, now),
        )
        await connection.execute(
            """
            INSERT INTO activity_summary_revisions(
                id, task_id, revision_number, finality, source_watermark,
                category_rule_version, revision_key, config, completed_at
            ) VALUES (
                'activity-security-revision', 'activity-security-task', 1, 'final', ?,
                ?, 'activity-security-revision-key', ?, ?
            )
            """,
            (
                "d" * 64,
                "c" * 64,
                json.dumps({"summary": f"api_key={provider_token}"}),
                now,
            ),
        )
        await connection.execute(
            """
            INSERT INTO activity_evidence_refs(
                owner_type, owner_id, ordinal, bucket_id, event_id,
                event_timestamp, event_digest, config
            ) VALUES (
                'revision', 'activity-security-revision', 0,
                'aw-watcher-window_local', 'event-security', ?, ?, ?
            )
            """,
            (
                now,
                "f" * 64,
                json.dumps({"fields_used": ["application"]}),
            ),
        )

    async with container.database.connect() as connection:
        evidence = await (
            await connection.execute(
                "SELECT owner_type, owner_id, config FROM activity_evidence_refs"
            )
        ).fetchone()
    assert evidence is not None
    assert dict(evidence) == {
        "owner_type": "revision",
        "owner_id": "activity-security-revision",
        "config": json.dumps({"fields_used": ["application"]}),
    }

    scan = await SecurityScanner(container.database).scan()

    assert {finding.kind for finding in scan.findings} == {
        "forbidden_sensor_field",
        "secret_value",
    }
    assert {
        (finding.table, finding.row_id, finding.field)
        for finding in scan.findings
        if finding.kind == "secret_value"
    } >= {
        ("runs", run.id, "result_summary"),
        ("connector_snapshots", container.default_workspace.id, "snapshot"),
        ("artifacts", artifact.id, "content"),
        ("activity_summary_revisions", "activity-security-revision", "config"),
    }
    assert all("raw content" not in finding.model_dump_json() for finding in scan.findings)
    assert all(provider_token not in finding.model_dump_json() for finding in scan.findings)
