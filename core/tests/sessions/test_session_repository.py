from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository
from weatherflow.sessions import (
    ConversationSession,
    ConversationSessionRepository,
    SessionNotFoundError,
    SessionVersionConflict,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def make_repositories(
    tmp_path: Path,
) -> tuple[
    Database,
    Workspace,
    ConversationSessionRepository,
    RunCoordinator,
]:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Project",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    sessions = ConversationSessionRepository(database)
    runs = RunRepository(database)
    return (
        database,
        workspace,
        sessions,
        RunCoordinator(
            database,
            runs,
            EventLedger(database),
            sessions=sessions,
        ),
    )


async def test_sessions_round_trip_rename_pin_and_sort(tmp_path: Path) -> None:
    _database, workspace, repository, _coordinator = await make_repositories(tmp_path)
    older = ConversationSession.new(workspace_id=workspace.id, title="Older")
    newer = ConversationSession.new(workspace_id=workspace.id, title="Newer")
    older = older.model_copy(
        update={
            "created_at": datetime.now(UTC) - timedelta(hours=2),
            "updated_at": datetime.now(UTC) - timedelta(hours=2),
        }
    )
    await repository.create(older)
    await repository.create(newer)

    renamed = await repository.update(
        older.id,
        workspace_id=workspace.id,
        expected_version=0,
        title="Pinned work",
        pinned=True,
    )

    assert renamed.title == "Pinned work"
    assert renamed.pinned is True
    assert renamed.version == 1
    assert await repository.get(older.id) == renamed
    assert [session.id for session in await repository.list(workspace.id)] == [
        older.id,
        newer.id,
    ]

    with pytest.raises(SessionVersionConflict):
        await repository.update(
            older.id,
            workspace_id=workspace.id,
            expected_version=0,
            title="Stale",
        )

    with pytest.raises(SessionNotFoundError):
        await repository.update(
            older.id,
            workspace_id="another-workspace",
            expected_version=renamed.version,
            title="Cross-workspace rename",
        )


async def test_run_attachment_updates_session_and_latest_run(tmp_path: Path) -> None:
    _database, workspace, sessions, coordinator = await make_repositories(tmp_path)
    session = ConversationSession.new(workspace_id=workspace.id, title="Release")
    await sessions.create(session)

    first = await coordinator.create_run(
        client_request_id="session-run-1",
        user_intent="Inspect the release",
        workspace_id=workspace.id,
        session_id=session.id,
    )
    second = await coordinator.create_run(
        client_request_id="session-run-2",
        user_intent="Summarize it",
        workspace_id=workspace.id,
        session_id=session.id,
    )

    listed = await sessions.list(workspace.id)
    assert first.session_id == session.id
    assert second.session_id == session.id
    assert listed[0].latest_run_id == second.id
    assert listed[0].updated_at >= session.updated_at


async def test_session_rejects_run_from_another_workspace(tmp_path: Path) -> None:
    _database, workspace, sessions, coordinator = await make_repositories(tmp_path)
    session = ConversationSession.new(workspace_id=workspace.id, title="Private")
    await sessions.create(session)

    with pytest.raises(LookupError):
        await coordinator.create_run(
            client_request_id="wrong-workspace",
            user_intent="Do not attach",
            workspace_id="another-workspace",
            session_id=session.id,
        )


async def test_delete_removes_session_runs_and_all_run_owned_durable_data(
    tmp_path: Path,
) -> None:
    database, workspace, sessions, coordinator = await make_repositories(tmp_path)
    deleted_session = ConversationSession.new(workspace_id=workspace.id, title="Delete me")
    retained_session = ConversationSession.new(workspace_id=workspace.id, title="Keep me")
    await sessions.create(deleted_session)
    await sessions.create(retained_session)
    deleted_run = await coordinator.create_run(
        client_request_id="deleted-session-run",
        user_intent="Private conversation",
        workspace_id=workspace.id,
        session_id=deleted_session.id,
    )
    retained_run = await coordinator.create_run(
        client_request_id="retained-session-run",
        user_intent="Retained conversation",
        workspace_id=workspace.id,
        session_id=retained_session.id,
    )
    now = datetime.now(UTC).isoformat()
    async with database.transaction() as connection:
        await connection.execute(
            """
            INSERT INTO actions(
                id, run_id, tool_id, arguments, effect, status, idempotency_key,
                preview, created_at, updated_at, version
            ) VALUES ('action-delete', ?, 'tool.delete', '{}', 'observe', 'proposed',
                'delete-key', '{}', ?, ?, 0)
            """,
            (deleted_run.id, now, now),
        )
        await connection.execute(
            """
            INSERT INTO approvals(
                id, action_id, run_id, status, requested_at, version
            ) VALUES ('approval-delete', 'action-delete', ?, 'pending', ?, 0)
            """,
            (deleted_run.id, now),
        )
        await connection.execute(
            """
            INSERT INTO capability_snapshots(
                id, run_id, catalog_revision, tools, digest, created_at
            ) VALUES ('snapshot-delete', ?, 'catalog-v1', '[]', 'digest', ?)
            """,
            (deleted_run.id, now),
        )
        await connection.execute(
            """
            INSERT INTO artifacts(
                id, run_id, name, media_type, digest, size_bytes,
                relative_path, validation, created_at
            ) VALUES ('artifact-delete', ?, 'private.txt', 'text/plain',
                'blob-digest', 7, 'sha256/bl/blob-digest', '{}', ?)
            """,
            (deleted_run.id, now),
        )
        await connection.execute(
            """
            INSERT INTO checkpoints(
                run_id, version, step_index, transcript, state, updated_at
            ) VALUES (?, 0, 0, '[]', '{}', ?)
            """,
            (deleted_run.id, now),
        )
        await connection.execute(
            """
            INSERT INTO checkpoint_quarantine(
                run_id, reason, raw_payload, payload_sha256, quarantined_at
            ) VALUES (?, 'private', X'01', 'payload-digest', ?)
            """,
            (deleted_run.id, now),
        )
        await connection.execute(
            """
            INSERT INTO provider_continuations(
                run_id, step_index, provider, model, schema_version, nonce,
                ciphertext, payload_sha256, created_at, expires_at
            ) VALUES (?, 1, 'minimax', 'MiniMax-M2', 1, ?, X'01', ?, ?, ?)
            """,
            (deleted_run.id, b"0" * 12, "0" * 64, now, now),
        )
        await connection.execute(
            """
            INSERT INTO run_model_routes(
                run_id, workspace_id, provider, model, bound_at
            ) VALUES (?, ?, 'echo', 'echo', ?)
            """,
            (deleted_run.id, workspace.id, now),
        )
        await connection.execute(
            """
            INSERT INTO run_connector_routes(
                run_id, workspace_id, connector, account_id, external_account_id,
                conversation_grant_revision, bound_at
            ) VALUES (?, ?, 'github', 'account', 'external', 1, ?)
            """,
            (deleted_run.id, workspace.id, now),
        )

    deletion = await sessions.delete(deleted_session.id, workspace_id=workspace.id)

    assert deletion.run_ids == (deleted_run.id,)
    assert [(blob.digest, blob.relative_path) for blob in deletion.artifacts] == [
        ("blob-digest", "sha256/bl/blob-digest")
    ]
    assert await sessions.get(deleted_session.id) is None
    assert await sessions.get(retained_session.id) is not None
    assert await coordinator.repository.get(deleted_run.id) is None
    assert await coordinator.repository.get(retained_run.id) is not None
    async with database.connect() as connection:
        for table in (
            "actions",
            "approvals",
            "capability_snapshots",
            "artifacts",
            "checkpoints",
            "checkpoint_quarantine",
            "provider_continuations",
            "run_model_routes",
            "run_connector_routes",
        ):
            row = await (
                await connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE run_id = ?",
                    (deleted_run.id,),
                )
            ).fetchone()
            assert row["count"] == 0, table
        event_count = await (
            await connection.execute(
                """
                SELECT COUNT(*) AS count FROM events
                WHERE stream_id = ? OR correlation_id = ?
                """,
                (deleted_run.id, deleted_run.id),
            )
        ).fetchone()
        foreign_key_violations = await (
            await connection.execute("PRAGMA foreign_key_check")
        ).fetchall()
    assert event_count["count"] == 0
    assert foreign_key_violations == []


async def test_delete_fails_closed_for_another_workspace(tmp_path: Path) -> None:
    _database, workspace, sessions, coordinator = await make_repositories(tmp_path)
    session = ConversationSession.new(workspace_id=workspace.id, title="Private")
    await sessions.create(session)
    run = await coordinator.create_run(
        client_request_id="cross-workspace-delete",
        user_intent="Keep private",
        workspace_id=workspace.id,
        session_id=session.id,
    )

    with pytest.raises(SessionNotFoundError):
        await sessions.delete(session.id, workspace_id="another-workspace")

    retained = await sessions.get(session.id)
    assert retained is not None
    assert retained.workspace_id == workspace.id
    assert retained.latest_run_id == run.id
    assert await coordinator.repository.get(run.id) == run
