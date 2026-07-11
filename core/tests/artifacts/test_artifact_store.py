import asyncio
from pathlib import Path

import aiosqlite
import pytest

from weatherflow.artifacts import ArtifactNameError, ArtifactRepository, ArtifactStore
from weatherflow.events import Event, EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace


async def setup_store(tmp_path: Path, ledger_type=EventLedger):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    ledger = ledger_type(database)
    repository = ArtifactRepository(database)
    store = ArtifactStore(database=database, repository=repository, ledger=ledger)
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
    )
    return store, repository, ledger, workspace, run


async def test_put_bytes_writes_verified_content_and_audit(tmp_path: Path) -> None:
    store, _, ledger, workspace, run = await setup_store(tmp_path)

    manifest = await store.put_bytes(
        run_id=run.id,
        workspace=workspace,
        name="release-notes.md",
        media_type="text/markdown",
        data=b"# Release\n",
        validation={"status": "validated"},
    )

    path = Path(workspace.artifact_root) / manifest.relative_path
    assert await asyncio.to_thread(path.read_bytes) == b"# Release\n"
    is_inside = await asyncio.to_thread(
        lambda: path.resolve().is_relative_to(Path(workspace.artifact_root).resolve())
    )
    assert is_inside
    assert manifest.size_bytes == 10
    assert manifest.relative_path == f"sha256/{manifest.digest[:2]}/{manifest.digest}"
    events = await ledger.list_correlation(run.id)
    assert events[-1].type == "artifact.created"
    assert events[-1].payload["digest"] == manifest.digest


async def test_identical_content_is_physically_deduplicated(tmp_path: Path) -> None:
    store, repository, _, workspace, run = await setup_store(tmp_path)

    first = await store.put_bytes(
        run_id=run.id,
        workspace=workspace,
        name="first.txt",
        media_type="text/plain",
        data=b"same",
    )
    second = await store.put_bytes(
        run_id=run.id,
        workspace=workspace,
        name="second.txt",
        media_type="text/plain",
        data=b"same",
    )

    assert first.id != second.id
    assert first.relative_path == second.relative_path
    assert len(await repository.list_run(run.id)) == 2
    files = await asyncio.to_thread(artifact_files, workspace.artifact_root)
    assert len(files) == 1


@pytest.mark.parametrize("name", ["", "../secret", "folder/file.txt", "."])
async def test_logical_name_cannot_control_path(tmp_path: Path, name: str) -> None:
    store, _, _, workspace, run = await setup_store(tmp_path)

    with pytest.raises(ArtifactNameError):
        await store.put_bytes(
            run_id=run.id,
            workspace=workspace,
            name=name,
            media_type="text/plain",
            data=b"secret",
        )


class FailingLedger(EventLedger):
    async def append_in(self, connection: aiosqlite.Connection, event: Event) -> None:
        if event.type == "artifact.created":
            raise RuntimeError("ledger failed")
        await super().append_in(connection, event)


async def test_failed_metadata_commit_cleans_new_blob(tmp_path: Path) -> None:
    store, repository, _, workspace, run = await setup_store(tmp_path, FailingLedger)

    with pytest.raises(RuntimeError, match="ledger failed"):
        await store.put_bytes(
            run_id=run.id,
            workspace=workspace,
            name="release.txt",
            media_type="text/plain",
            data=b"new blob",
        )

    assert await repository.list_run(run.id) == []
    files = await asyncio.to_thread(artifact_files, workspace.artifact_root)
    assert files == []


def artifact_files(root: str) -> list[Path]:
    return [path for path in Path(root).rglob("*") if path.is_file()]
