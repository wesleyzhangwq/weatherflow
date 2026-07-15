import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from weatherflow.artifacts import ArtifactRepository, ArtifactStore
from weatherflow.capabilities.builtin import DeveloperExecutor, developer_tool_specs
from weatherflow.capabilities.builtin.developer import _sanitized_path
from weatherflow.events import EventLedger
from weatherflow.runs import Run, RunRepository
from weatherflow.runtime import ToolExecutionContext
from weatherflow.sandbox import (
    MacOSSeatbeltSandbox,
    SandboxNetworkMode,
    SandboxResult,
    SandboxUnavailableError,
)
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace, WorkspaceRepository


class RecordingSandbox:
    backend_id = "recording-sandbox"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.requests = []

    def is_available(self) -> bool:
        return self.available

    async def execute(self, request):
        if not self.available:
            raise SandboxUnavailableError("sandbox unavailable")
        self.requests.append(request)
        return SandboxResult(
            backend_id=self.backend_id,
            argv=request.argv,
            returncode=0,
            stdout="sandboxed\n",
            stderr="",
            duration_ms=1,
            network=request.network,
        )


async def setup(tmp_path: Path, *, sandbox=None):
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
    return (
        project,
        workspace,
        DeveloperExecutor(
            repository,
            sandbox=sandbox or RecordingSandbox(),
        ),
    )


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
    assert spec("developer.run_command").input_schema["properties"]["network"] == {
        "type": "string",
        "enum": ["offline", "loopback"],
        "default": "offline",
        "description": "Network access for the sandboxed command; never permits external hosts",
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


async def test_command_execution_only_accepts_classified_read_only_forms(tmp_path: Path) -> None:
    project, workspace, executor = await setup(tmp_path)
    context = ToolExecutionContext(run_id="run-1", workspace_id=workspace.id)

    result = await executor.execute(
        spec("developer.run_command"),
        {"argv": ["python", "--version"]},
        context,
    )
    assert result.output["returncode"] == 0

    await asyncio.to_thread(
        subprocess.run,
        ["git", "init", str(project)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    status = await executor.execute(
        spec("developer.run_command"),
        {"argv": ["git", "status", "--short"]},
        context,
    )
    assert status.output["returncode"] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["make", "test"],
        ["pnpm", "run", "build"],
        ["npm", "test"],
        ["uv", "run", "pytest", "-q"],
        ["cargo", "test"],
    ],
)
async def test_reviewed_build_and_test_frontends_enter_the_os_sandbox(
    tmp_path: Path,
    argv: list[str],
) -> None:
    sandbox = RecordingSandbox()
    _, workspace, executor = await setup(tmp_path, sandbox=sandbox)

    result = await executor.execute(
        spec("developer.run_command"),
        {"argv": argv},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    assert result.output["sandbox"]["backend"] == sandbox.backend_id
    assert result.output["sandbox"]["network"] == "offline"
    assert len(sandbox.requests) == 1
    assert sandbox.requests[0].writable_roots == workspace.action_roots


async def test_explicit_workspace_script_enters_the_os_sandbox(tmp_path: Path) -> None:
    sandbox = RecordingSandbox()
    project, workspace, executor = await setup(tmp_path, sandbox=sandbox)
    script = project / "scripts" / "check.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)

    await executor.execute(
        spec("developer.run_command"),
        {"argv": ["./scripts/check.sh"]},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    assert sandbox.requests[0].argv[0] == str(script.resolve())


async def test_declared_loopback_mode_is_frozen_into_the_sandbox_request(
    tmp_path: Path,
) -> None:
    sandbox = RecordingSandbox()
    _, workspace, executor = await setup(tmp_path, sandbox=sandbox)

    await executor.execute(
        spec("developer.run_command"),
        {"argv": ["make", "test"], "network": "loopback"},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    assert sandbox.requests[0].network is SandboxNetworkMode.LOOPBACK


async def test_declared_pyenv_root_survives_a_temporary_sandbox_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = RecordingSandbox()
    _, workspace, executor = await setup(tmp_path, sandbox=sandbox)
    pyenv_root = tmp_path / "host-tools" / ".pyenv"
    executable = pyenv_root / "shims" / "python"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    sandbox_home = tmp_path / "sandbox-home"
    sandbox_home.mkdir()
    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("PYENV_ROOT", str(pyenv_root))
    monkeypatch.setenv("PATH", str(executable.parent))

    await executor.execute(
        spec("developer.run_command"),
        {"argv": ["python", "--version"]},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    request = sandbox.requests[0]
    assert request.argv[0] == str(executable)
    assert request.environment["PYENV_ROOT"] == str(pyenv_root.resolve())
    assert str(pyenv_root.resolve()) in request.readable_roots


async def test_nvm_toolchain_is_derived_from_path_under_a_temporary_sandbox_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = RecordingSandbox()
    _, workspace, executor = await setup(tmp_path, sandbox=sandbox)
    versions_root = tmp_path / "host-tools" / ".nvm" / "versions"
    executable = versions_root / "node" / "v1.2.3" / "bin" / "npm"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    sandbox_home = tmp_path / "sandbox-home"
    sandbox_home.mkdir()
    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.delenv("PYENV_ROOT", raising=False)
    monkeypatch.setenv("PATH", str(executable.parent))

    await executor.execute(
        spec("developer.run_command"),
        {"argv": ["npm", "test"]},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    request = sandbox.requests[0]
    assert request.argv[0] == str(executable)
    assert str(versions_root.resolve()) in request.readable_roots


@pytest.mark.skipif(
    sys.platform != "darwin" or bool(os.environ.get("WF_SANDBOX_ACTIVE")),
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_developer_make_runs_a_real_build_inside_the_os_sandbox(
    tmp_path: Path,
) -> None:
    project, workspace, executor = await setup(
        tmp_path,
        sandbox=MacOSSeatbeltSandbox(),
    )
    (project / "Makefile").write_text("test:\n\t@printf 'sandbox-build-ok\\n' > build-result.txt\n")

    result = await executor.execute(
        spec("developer.run_command"),
        {"argv": ["make", "test"]},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    assert result.output["returncode"] == 0
    assert result.output["sandbox"]["backend"] == "macos-seatbelt-v1"
    assert (project / "build-result.txt").read_text() == "sandbox-build-ok\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-c", "from pathlib import Path; Path('/tmp/escaped').write_text('x')"],
        ["python3", "task.py"],
        ["git", "push", "origin", "main"],
        ["git", "-C", "/tmp", "status"],
        ["npm", "install", "left-pad"],
        ["pnpm", "add", "left-pad"],
        ["uv", "pip", "install", "requests"],
        ["uv", "run", "--with", "requests", "python", "task.py"],
        ["npx", "eslint", "."],
        ["make", "release"],
        ["sh", "-c", "echo unsafe"],
    ],
)
async def test_unclassified_or_side_effecting_commands_fail_closed(
    tmp_path: Path,
    argv: list[str],
) -> None:
    _, workspace, executor = await setup(tmp_path)
    context = ToolExecutionContext(run_id="run-1", workspace_id=workspace.id)

    with pytest.raises(PermissionError):
        await executor.execute(spec("developer.run_command"), {"argv": argv}, context)


async def test_workspace_executables_cannot_shadow_reviewed_frontends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = RecordingSandbox()
    project, workspace, executor = await setup(tmp_path, sandbox=sandbox)
    binary_directory = project / "bin"
    binary_directory.mkdir()
    fake_python = binary_directory / "python"
    fake_python.write_text("#!/bin/sh\necho escaped\n")
    fake_python.chmod(0o755)
    (project / "nested").mkdir()
    monkeypatch.setenv("PATH", f"{binary_directory}{os.pathsep}{os.environ['PATH']}")

    await executor.execute(
        spec("developer.run_command"),
        {"argv": ["python", "--version"], "cwd": "nested"},
        ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
    )

    selected = await asyncio.to_thread(Path(sandbox.requests[0].argv[0]).resolve)
    fake_resolved = await asyncio.to_thread(fake_python.resolve)
    assert selected != fake_resolved


async def test_missing_os_sandbox_fails_closed_without_subprocess_fallback(
    tmp_path: Path,
) -> None:
    sandbox = RecordingSandbox(available=False)
    _, workspace, executor = await setup(tmp_path, sandbox=sandbox)

    with pytest.raises(SandboxUnavailableError):
        await executor.execute(
            spec("developer.run_command"),
            {"argv": ["make", "test"]},
            ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
        )
    assert sandbox.requests == []


async def test_subprocess_path_excludes_workspace_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, workspace, _ = await setup(tmp_path)
    binary_directory = project / "bin"
    binary_directory.mkdir()
    trusted_directory = tmp_path / "trusted-bin"
    trusted_directory.mkdir()
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(binary_directory), "", str(trusted_directory))),
    )

    assert _sanitized_path(workspace) == str(trusted_directory)


async def test_git_metadata_cannot_escape_workspace(tmp_path: Path) -> None:
    project, workspace, executor = await setup(tmp_path)
    outside_git = tmp_path / "outside.git"
    outside_git.mkdir()
    (project / ".git").write_text(f"gitdir: {outside_git}\n")

    with pytest.raises(PermissionError, match="Git metadata"):
        await executor.execute(
            spec("developer.run_command"),
            {"argv": ["git", "status", "--short"]},
            ToolExecutionContext(run_id="run-1", workspace_id=workspace.id),
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
