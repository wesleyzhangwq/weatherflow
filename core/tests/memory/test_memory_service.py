from pathlib import Path

import pytest

from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.memory import (
    MemorySourceError,
    MemoryStore,
    ProfileAssertionStatus,
    ProfileVersionConflict,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def setup_memory(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Memory",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
    )
    await WorkspaceRepository(database).create(workspace)
    ledger = EventLedger(database)
    memory = MemoryStore(database=database, ledger=ledger)
    return database, workspace, ledger, memory


async def append_source(
    ledger: EventLedger,
    workspace_id: str,
    *,
    event_type: str = "run.outcome_observed",
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> Event:
    event = Event.new(
        type=event_type,
        actor=Actor.USER,
        stream_kind="workspace",
        stream_id=workspace_id,
        correlation_id=workspace_id,
        payload={"result": "source fact"},
        sensitivity=sensitivity,
    )
    await ledger.append(event)
    return event


async def test_episode_requires_real_non_secret_workspace_sources(tmp_path: Path) -> None:
    _, workspace, ledger, memory = await setup_memory(tmp_path)
    secret = await append_source(
        ledger,
        workspace.id,
        event_type="credential.reference_observed",
        sensitivity=Sensitivity.SECRET_REF,
    )
    other = Workspace.new(
        name="Other",
        action_roots=[tmp_path / "other"],
        internal_root=tmp_path / "other-internal",
        artifact_root=tmp_path / "other-artifacts",
    )
    await WorkspaceRepository(memory.database).create(other)
    foreign = await append_source(ledger, other.id)

    for source_id in ("missing", secret.id, foreign.id):
        with pytest.raises(MemorySourceError):
            await memory.remember_episode(
                workspace_id=workspace.id,
                summary="Never retain an ungrounded memory",
                source_event_ids=(source_id,),
            )

    source = await append_source(ledger, workspace.id)
    episode = await memory.remember_episode(
        workspace_id=workspace.id,
        summary="The release workflow succeeds when validation runs before packaging.",
        source_event_ids=(source.id,),
        tags=("release", "validation"),
    )

    assert episode.source_event_ids == (source.id,)
    assert (await memory.episodes.list_workspace(workspace.id)) == [episode]


async def test_profile_assertions_are_editable_with_versioned_audit(tmp_path: Path) -> None:
    _, workspace, ledger, memory = await setup_memory(tmp_path)
    source = await append_source(ledger, workspace.id)
    assertion = await memory.create_assertion(
        workspace_id=workspace.id,
        claim="User prefers compact release reports.",
        confidence=0.7,
        evidence_event_ids=(source.id,),
        origin="user",
    )

    updated = await memory.update_assertion(
        assertion.id,
        expected_version=0,
        claim="User prefers compact, evidence-backed release reports.",
        confidence=0.9,
    )

    assert updated.version == 1
    assert updated.confidence == 0.9
    with pytest.raises(ProfileVersionConflict):
        await memory.update_assertion(
            assertion.id,
            expected_version=0,
            status=ProfileAssertionStatus.RETRACTED,
        )
    retracted = await memory.update_assertion(
        assertion.id,
        expected_version=1,
        status=ProfileAssertionStatus.RETRACTED,
    )
    assert retracted.status is ProfileAssertionStatus.RETRACTED
    audit = await ledger.list_stream("profile_assertion", assertion.id)
    assert [event.type for event in audit] == [
        "memory.profile_assertion_created",
        "memory.profile_assertion_updated",
        "memory.profile_assertion_updated",
    ]
    assert all("claim" not in event.payload for event in audit)


async def test_derived_index_can_be_deleted_and_rebuilt(tmp_path: Path) -> None:
    database, workspace, ledger, memory = await setup_memory(tmp_path)
    source = await append_source(ledger, workspace.id)
    await memory.remember_episode(
        workspace_id=workspace.id,
        summary="Release validation should run before package creation.",
        source_event_ids=(source.id,),
        tags=("release",),
    )
    await memory.create_assertion(
        workspace_id=workspace.id,
        claim="Prefer compact evidence-backed summaries.",
        confidence=0.8,
        evidence_event_ids=(source.id,),
        origin="user",
    )

    before = await memory.recall(workspace.id, "release validation compact", limit=5)
    async with database.transaction() as connection:
        await connection.execute(
            "DELETE FROM memory_search_index WHERE workspace_id = ?", (workspace.id,)
        )
    assert await memory.recall(workspace.id, "release validation compact", limit=5) == ()

    rebuilt = await memory.rebuild_index(workspace.id)
    after = await memory.recall(workspace.id, "release validation compact", limit=5)

    assert rebuilt == 2
    assert [(item.kind, item.text) for item in after] == [(item.kind, item.text) for item in before]


async def test_recall_is_bounded_and_excludes_retracted_assertions(tmp_path: Path) -> None:
    _, workspace, ledger, memory = await setup_memory(tmp_path)
    source = await append_source(ledger, workspace.id)
    for index in range(8):
        await memory.remember_episode(
            workspace_id=workspace.id,
            summary=f"Release lesson {index}: validate every package before shipping.",
            source_event_ids=(source.id,),
        )
    assertion = await memory.create_assertion(
        workspace_id=workspace.id,
        claim="Never show this retracted release preference.",
        confidence=0.6,
        evidence_event_ids=(source.id,),
        origin="user",
    )
    await memory.update_assertion(
        assertion.id,
        expected_version=0,
        status=ProfileAssertionStatus.RETRACTED,
    )

    recalled = await memory.recall(
        workspace.id,
        "release validate package",
        limit=3,
        max_chars=180,
    )

    assert len(recalled) <= 3
    assert sum(len(item.text) for item in recalled) <= 180
    assert all("retracted" not in item.text for item in recalled)
