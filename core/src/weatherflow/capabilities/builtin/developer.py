import asyncio
import difflib
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from weatherflow.artifacts import ArtifactManifest, ArtifactStore
from weatherflow.capabilities.models import (
    IdempotencyKind,
    ToolEffect,
    ToolSpec,
)
from weatherflow.runtime import ToolExecutionContext, ToolExecutionResult
from weatherflow.workspaces import Workspace, WorkspaceRepository

VERSION_ONLY_COMMANDS = frozenset({"python", "python3", "uv", "npm", "pnpm", "make"})
SAFE_GIT_STATUS_FLAGS = frozenset({"--short", "--branch", "--porcelain"})
MAX_ARGV_ITEMS = 16
MAX_ARGUMENT_CHARS = 4_096
MAX_FILE_BYTES = 1_000_000
MAX_OUTPUT_CHARS = 16_000


def developer_tool_specs() -> tuple[ToolSpec, ...]:
    common = {"source": "builtin.developer", "source_version": "1"}
    return (
        ToolSpec(
            tool_id="developer.read_file",
            description="Read a UTF-8 file inside an authorized Workspace root",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File path relative to the authorized Workspace root, "
                            "or an absolute path inside that root"
                        ),
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.OBSERVE,
            required_scopes=frozenset({"workspace:read"}),
            **common,
        ),
        ToolSpec(
            tool_id="developer.write_file",
            description="Atomically write a UTF-8 file with diff and recovery metadata",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Destination path inside the Workspace root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete UTF-8 file content to write",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.WORKSPACE_WRITE,
            required_scopes=frozenset({"workspace:write"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
        ToolSpec(
            tool_id="developer.write_artifact",
            description="Commit a validated content-addressed Run artifact",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "media_type": {"type": "string"},
                    "content": {"type": "string"},
                    "validation": {"type": "object"},
                },
                "required": ["name", "media_type", "content"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.WORKSPACE_WRITE,
            required_scopes=frozenset({"workspace:write"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
        ToolSpec(
            tool_id="developer.git_status",
            description="Read porcelain Git status for an authorized Workspace root",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.EXECUTE,
            required_scopes=frozenset({"workspace:execute"}),
            **common,
        ),
        ToolSpec(
            tool_id="developer.run_command",
            description=(
                "Run a narrowly classified read-only command without a shell. "
                "Arbitrary interpreters, project scripts, installs, Git mutations, "
                "and unknown command forms fail closed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "Command and arguments as an argv array; no shell",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory inside the Workspace",
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.EXECUTE,
            required_scopes=frozenset({"workspace:execute"}),
            timeout_seconds=300,
            **common,
        ),
    )


class DeveloperExecutor:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        *,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.artifacts = artifacts

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        workspace = await self.workspaces.get(context.workspace_id)
        if workspace is None:
            raise LookupError(context.workspace_id)
        if tool.tool_id == "developer.read_file":
            path = await asyncio.to_thread(_resolve_path, workspace, str(arguments["path"]))
            content = await asyncio.to_thread(_read_text, path)
            return ToolExecutionResult(output={"path": str(path), "content": content})
        if tool.tool_id == "developer.write_file":
            path = await asyncio.to_thread(_resolve_path, workspace, str(arguments["path"]))
            output = await asyncio.to_thread(_write_text, path, str(arguments["content"]))
            return ToolExecutionResult(output=output)
        if tool.tool_id == "developer.git_status":
            root = Path(workspace.action_roots[0])
            return await self._run(
                ["git", "status", "--short"], root, tool.timeout_seconds, workspace
            )
        if tool.tool_id == "developer.run_command":
            argv = arguments.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(item, str) for item in argv)
            ):
                raise ValueError("argv must be a non-empty string array")
            cwd_value = str(arguments.get("cwd", workspace.action_roots[0]))
            cwd = await asyncio.to_thread(_resolve_path, workspace, cwd_value)
            return await self._run(argv, cwd, tool.timeout_seconds, workspace)
        if tool.tool_id == "developer.write_artifact":
            return await self._write_artifact(arguments, context, workspace)
        raise LookupError(tool.tool_id)

    async def _write_artifact(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        workspace: Workspace,
    ) -> ToolExecutionResult:
        if self.artifacts is None:
            raise RuntimeError("Artifact Store is not configured")
        name = arguments.get("name")
        media_type = arguments.get("media_type")
        content = arguments.get("content")
        validation = arguments.get("validation", {})
        if not isinstance(name, str) or not name or len(name) > 255:
            raise ValueError("name must be a bounded string")
        if not isinstance(media_type, str) or not media_type or len(media_type) > 200:
            raise ValueError("media_type must be a bounded string")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        encoded = content.encode()
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("artifact exceeds size limit")
        if not isinstance(validation, dict):
            raise ValueError("validation must be an object")
        if len(json.dumps(validation, ensure_ascii=False)) > MAX_OUTPUT_CHARS:
            raise ValueError("validation exceeds size limit")
        digest = hashlib.sha256(encoded).hexdigest()
        existing = next(
            (
                manifest
                for manifest in await self.artifacts.repository.list_run(context.run_id)
                if manifest.name == name
                and manifest.digest == digest
                and manifest.validation == validation
            ),
            None,
        )
        manifest = existing or await self.artifacts.put_bytes(
            run_id=context.run_id,
            workspace=workspace,
            name=name,
            media_type=media_type,
            data=encoded,
            validation=validation,
        )
        return _artifact_result(manifest)

    async def _run(
        self,
        argv: list[str],
        cwd: Path,
        timeout_seconds: int,
        workspace: Workspace,
    ) -> ToolExecutionResult:
        execution_argv = _classify_command(argv, cwd, workspace)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "CI"}
        }
        environment["PATH"] = _sanitized_path(workspace)
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        with tempfile.TemporaryDirectory(prefix="weatherflow-command-home-") as temporary_home:
            environment["HOME"] = temporary_home
            process = await asyncio.create_subprocess_exec(
                *execution_argv,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(f"command exceeded {timeout_seconds}s") from None
        return ToolExecutionResult(
            output={
                "argv": argv,
                "returncode": process.returncode,
                "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS],
                "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT_CHARS],
                "truncated": len(stdout) > MAX_OUTPUT_CHARS or len(stderr) > MAX_OUTPUT_CHARS,
            }
        )


def _classify_command(argv: list[str], cwd: Path, workspace: Workspace) -> list[str]:
    if (
        not argv
        or len(argv) > MAX_ARGV_ITEMS
        or any(not item or "\x00" in item or len(item) > MAX_ARGUMENT_CHARS for item in argv)
    ):
        raise PermissionError("command arguments are empty, malformed, or exceed limits")

    command = argv[0]
    if command in VERSION_ONLY_COMMANDS:
        expected_flags = {"--version", "-V"} if command.startswith("python") else {"--version"}
        if len(argv) != 2 or argv[1] not in expected_flags:
            raise PermissionError(
                f"{command} project execution is not available without an OS sandbox"
            )
        return [_resolve_executable(command, workspace), argv[1]]

    if command == "git":
        if argv == ["git", "--version"]:
            return [_resolve_executable(command, workspace), "--version"]
        if len(argv) >= 2 and argv[1] == "status":
            flags = argv[2:]
            if len(flags) == len(set(flags)) and all(
                flag in SAFE_GIT_STATUS_FLAGS for flag in flags
            ):
                _require_scoped_git_metadata(cwd, workspace)
                return [
                    _resolve_executable(command, workspace),
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "status.submoduleSummary=false",
                    "--no-pager",
                    "status",
                    "--ignore-submodules=all",
                    *flags,
                ]
        raise PermissionError("Git mutations and unclassified Git arguments require approval")

    raise PermissionError(f"command {command} is not classified for sandbox execution")


def _resolve_executable(command: str, workspace: Workspace) -> str:
    located = shutil.which(command)
    if located is None:
        raise FileNotFoundError(command)
    resolved = Path(located).resolve()
    if workspace.allows_action_path(resolved):
        raise PermissionError(f"Workspace executable {command} is not trusted")
    return str(resolved)


def _sanitized_path(workspace: Workspace) -> str:
    directories: list[str] = []
    for value in os.environ.get("PATH", "").split(os.pathsep):
        if not value:
            continue
        directory = Path(value).expanduser().resolve()
        if workspace.allows_action_path(directory):
            continue
        directories.append(str(directory))
    return os.pathsep.join(directories)


def _require_scoped_git_metadata(cwd: Path, workspace: Workspace) -> None:
    current = cwd.resolve()
    while workspace.allows_action_path(current):
        marker = current / ".git"
        if marker.exists() or marker.is_symlink():
            if marker.is_dir():
                metadata = marker.resolve()
            elif marker.is_file() and marker.stat().st_size <= 4_096:
                declaration = marker.read_text(encoding="utf-8").strip()
                prefix = "gitdir:"
                if not declaration.lower().startswith(prefix):
                    raise PermissionError("Git metadata declaration is malformed")
                value = declaration[len(prefix) :].strip()
                if not value:
                    raise PermissionError("Git metadata declaration is empty")
                metadata = Path(value)
                if not metadata.is_absolute():
                    metadata = marker.parent / metadata
                metadata = metadata.resolve()
            else:
                raise PermissionError("Git metadata marker is unsupported")
            if not workspace.allows_action_path(metadata):
                raise PermissionError("Git metadata resolves outside the authorized Workspace")
            return
        if current.parent == current:
            break
        current = current.parent
    raise PermissionError("Git status requires repository metadata inside the Workspace")


def _resolve_path(workspace: Workspace, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(workspace.action_roots[0]) / candidate
    resolved = candidate.resolve()
    if not workspace.allows_action_path(resolved):
        raise PermissionError(value)
    return resolved


def _read_text(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file is missing, not regular, or too large")
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> dict[str, Any]:
    encoded = content.encode()
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("file exceeds size limit")
    before = path.read_text(encoding="utf-8") if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    diff = "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        )
    )
    return {
        "path": str(path),
        "bytes": len(encoded),
        "before_digest": (
            hashlib.sha256(before.encode()).hexdigest() if before is not None else None
        ),
        "after_digest": hashlib.sha256(encoded).hexdigest(),
        "diff": diff[:MAX_OUTPUT_CHARS],
        "recovery": {"previous_content_available": before is not None},
    }


def _artifact_result(manifest: ArtifactManifest) -> ToolExecutionResult:
    return ToolExecutionResult(
        output={
            "artifact_id": manifest.id,
            "name": manifest.name,
            "media_type": manifest.media_type,
            "digest": manifest.digest,
            "size_bytes": manifest.size_bytes,
            "validation": manifest.validation,
        },
        artifact_ids=(manifest.id,),
    )
