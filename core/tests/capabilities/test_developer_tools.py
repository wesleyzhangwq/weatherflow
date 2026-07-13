from pathlib import Path

import pytest

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities.builtin import DeveloperExecutor, developer_tool_specs
from weatherflow.capabilities.builtin.developer import ALLOWED_COMMANDS
from weatherflow.events import EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime import ToolExecutionContext
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


async def setup(tmp_path: Path):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    project = tmp_path / "project"
    project.mkdir()
    workspace = Workspace.new(
        name="Developer",
        action_roots=[project],
        internal_root=tmp_path / ".weatherflow",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:read", "workspace:write", "workspace:execute"},
    )
    repository = WorkspaceRepository(database)
    await repository.create(workspace)
    return project, workspace, DeveloperExecutor(repository)


def spec(tool_id: str):
    return next(item for item in developer_tool_specs() if item.tool_id == tool_id)


def test_developer_tool_schemas_describe_every_required_argument() -> None:
    for tool in developer_tool_specs():
        required = set(tool.input_schema.get("required", ()))
        properties = set(tool.input_schema.get("properties", {}))
        assert required <= properties, tool.tool_id

    assert spec("developer.read_file").input_schema["properties"]["path"] == {
        "type": "string",
        "description": (
            "File path relative to the authorized Workspace root, "
            "or an absolute path inside that root"
        ),
    }


async def test_read_and_write_stay_inside_workspace(tmp_path: Path) -> None:
    project, workspace, executor = await setup(tmp_path)
    context = ToolExecutionContext(run_id="run-1", workspace_id=workspace.id)

    written = await executor.execute(
        spec("developer.write_file"),
        {"path": "release.md", "content": "# Release\n"},
        context,
    )
    read = await executor.execute(spec("developer.read_file"), {"path": "release.md"}, context)

    assert (project / "release.md").read_text() == "# Release\n"
    assert read.output["content"] == "# Release\n"
    assert written.output["before_digest"] is None
    assert len(written.output["after_digest"]) == 64
    assert "diff" in written.output


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd"])
async def test_path_escape_is_rejected(tmp_path: Path, path: str) -> None:
    _, workspace, executor = await setup(tmp_path)

    with pytest.raises(PermissionError):
        await executor.execute(
            spec("developer.read_file"),
            {"path": path},
            ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
        )


async def test_internal_root_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    project, workspace, executor = await setup(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (project / "link").symlink_to(secret)
    context = ToolExecutionContext(run_id="run-1", workspace_id=workspace.id)

    with pytest.raises(PermissionError):
        await executor.execute(spec("developer.read_file"), {"path": "link"}, context)
    with pytest.raises(PermissionError):
        await executor.execute(
            spec("developer.read_file"),
            {"path": str(Path(workspace.internal_root) / "weatherflow.db")},
            context,
        )


async def test_command_execution_is_allowlisted_and_bounded(tmp_path: Path) -> None:
    _, workspace, executor = await setup(tmp_path)
    context = ToolExecutionContext(run_id="run-1", workspace_id=workspace.id)

    result = await executor.execute(
        spec("developer.run_command"),
        {"argv": ["python", "-c", "print('ok')"]},
        context,
    )
    assert result.output["returncode"] == 0
    assert result.output["stdout"] == "ok\n"

    assert "pnpm" in ALLOWED_COMMANDS

    with pytest.raises(PermissionError):
        await executor.execute(
            spec("developer.run_command"), {"argv": ["sh", "-c", "echo unsafe"]}, context
        )


async def test_release_artifact_is_content_addressed_with_validation(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "artifact.db")
    await database.initialize()
    workspace = Workspace.new(
        name="Artifact",
        action_roots=[tmp_path / "project"],
        internal_root=tmp_path / "internal",
        artifact_root=tmp_path / "artifacts",
        granted_scopes={"workspace:write"},
    )
    workspaces = WorkspaceRepository(database)
    await workspaces.create(workspace)
    run = Run.new(
        client_request_id="artifact-request",
        user_intent="prepare release",
        workspace_id=workspace.id,
    )
    async with database.transaction() as connection:
        await RunRepository(database).create_in(connection, run)
    repository = ArtifactRepository(database)
    executor = DeveloperExecutor(
        workspaces,
        artifacts=ArtifactStore(
            database=database,
            repository=repository,
            ledger=EventLedger(database),
        ),
    )

    result = await executor.execute(
        spec("developer.write_artifact"),
        {
            "name": "release-checklist.md",
            "media_type": "text/markdown",
            "content": "# Release checklist\n- tests pass\n",
            "validation": {"status": "passed", "checks": 1},
        },
        ToolExecutionContext(run_id=run.id, workspace_id=workspace.id),
    )

    manifest = await repository.get(result.artifact_ids[0])
    assert manifest is not None
    assert manifest.validation == {"status": "passed", "checks": 1}
    assert manifest.digest == result.output["digest"]
