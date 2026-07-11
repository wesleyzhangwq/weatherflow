from pathlib import Path

import pytest

from weatherflow.capabilities import (
    CapabilitySnapshotRepository,
    DuplicateCapabilitySnapshot,
    RunCapabilitySnapshot,
    ToolEffect,
    ToolSpec,
)
from weatherflow.runs import Run, RunRepository
from weatherflow.storage import Database


def tool(tool_id: str, scopes: set[str] | None = None) -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id,
        description=tool_id,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.OBSERVE,
        required_scopes=frozenset(scopes or set()),
        source="test",
        source_version="1",
    )


def test_freeze_sorts_tools_and_hashes_canonical_schema() -> None:
    first = RunCapabilitySnapshot.freeze(
        run_id="run-1",
        catalog_revision="revision-1",
        tools=[tool("z", {"b", "a"}), tool("a")],
    )
    second = RunCapabilitySnapshot.freeze(
        run_id="run-1",
        catalog_revision="revision-1",
        tools=[tool("a"), tool("z", {"a", "b"})],
    )

    assert [item.tool_id for item in first.tools] == ["a", "z"]
    assert first.digest == second.digest
    assert len(first.digest) == 64


async def test_repository_round_trips_and_enforces_one_snapshot_per_run(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    run = Run.new(
        client_request_id="request-1",
        user_intent="ship release",
        workspace_id="workspace-1",
    )
    repository = CapabilitySnapshotRepository(database)
    first = RunCapabilitySnapshot.freeze(
        run_id=run.id,
        catalog_revision="revision-1",
        tools=[tool("observe")],
    )
    duplicate = RunCapabilitySnapshot.freeze(
        run_id=run.id,
        catalog_revision="revision-2",
        tools=[tool("another")],
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
        await repository.create_in(connection, first)

    assert await repository.get(first.id) == first
    assert await repository.get_by_run_id(run.id) == first

    with pytest.raises(DuplicateCapabilitySnapshot):
        async with database.transaction() as connection:
            await repository.create_in(connection, duplicate)
