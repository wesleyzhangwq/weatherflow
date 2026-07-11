from pathlib import Path

import pytest

from weatherflow.storage import Database
from weatherflow.workspaces import DuplicateWorkspaceError, Workspace, WorkspaceRepository


async def test_workspace_repository_round_trips_and_lists(tmp_path: Path) -> None:
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    repository = WorkspaceRepository(database)
    workspace = Workspace.new(
        name="WeatherFlow",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:write"},
        installed_packs={"developer"},
    )

    await repository.create(workspace)

    assert await repository.get(workspace.id) == workspace
    assert await repository.list_all() == [workspace]
    assert workspace.version == 0
    assert workspace.created_at == workspace.updated_at

    with pytest.raises(DuplicateWorkspaceError):
        await repository.create(workspace)
