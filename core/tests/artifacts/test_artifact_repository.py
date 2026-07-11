from pathlib import Path

import pytest
from pydantic import ValidationError

from weatherflow.artifacts import (
    ArtifactManifest,
    ArtifactRepository,
    DuplicateArtifactError,
)
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database


def manifest(run_id: str) -> ArtifactManifest:
    return ArtifactManifest.new(
        run_id=run_id,
        name="release-notes.md",
        media_type="text/markdown",
        digest="a" * 64,
        size_bytes=12,
        relative_path=f"sha256/aa/{'a' * 64}",
        validation={"status": "validated", "validator": "markdown"},
    )


def test_manifest_is_frozen_and_keeps_validation_metadata() -> None:
    value = manifest("run-1")

    assert len(value.id) == 26
    assert value.validation == {"status": "validated", "validator": "markdown"}
    with pytest.raises(ValidationError):
        value.size_bytes = 13


async def test_repository_round_trip_and_list_by_run(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    value = manifest(run.id)
    repository = ArtifactRepository(database)
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
        await repository.create_in(connection, value)

    assert await repository.get(value.id) == value
    assert await repository.list_run(run.id) == [value]

    with pytest.raises(DuplicateArtifactError):
        async with database.transaction() as connection:
            await repository.create_in(connection, value)
