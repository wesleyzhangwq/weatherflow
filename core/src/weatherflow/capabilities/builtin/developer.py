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
from weatherflow.sandbox import (
    SandboxBackend,
    SandboxLimits,
    SandboxNetworkMode,
    SandboxRequest,
    SandboxUnavailableError,
)
from weatherflow.workspaces import NetworkPolicy, Workspace, WorkspaceRepository

PYTHON_COMMANDS = frozenset({"python", "python3"})
PACKAGE_SCRIPT_COMMANDS = frozenset({"npm", "pnpm"})
PYTHON_MODULES = frozenset({"compileall", "pytest", "unittest"})
CARGO_SUBCOMMANDS = frozenset({"build", "check", "clippy", "doc", "fmt", "metadata", "run", "test"})
FORBIDDEN_MAKE_TARGETS = frozenset({"deploy", "install", "publish", "push", "release", "uninstall"})
SAFE_GIT_STATUS_FLAGS = frozenset({"--short", "--branch", "--porcelain"})
MAX_ARGV_ITEMS = 64
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
                "Run a reviewed project script, build, or test frontend inside the "
                "macOS OS sandbox. Shell strings, installs, Git remote mutations, "
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
                    "network": {
                        "type": "string",
                        "enum": ["offline", "loopback"],
                        "default": "offline",
                        "description": (
                            "Network access for the sandboxed command; never permits external hosts"
                        ),
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            effect=ToolEffect.EXECUTE,
            required_scopes=frozenset({"workspace:execute"}),
            timeout_seconds=300,
            source="builtin.developer",
            source_version="2",
        ),
    )


class DeveloperExecutor:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        *,
        artifacts: ArtifactStore | None = None,
        sandbox: SandboxBackend | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.artifacts = artifacts
        self.sandbox = sandbox

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
                ["git", "status", "--short"],
                root,
                tool.timeout_seconds,
                workspace,
                writable=False,
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
            network = SandboxNetworkMode(str(arguments.get("network", "offline")))
            if network is SandboxNetworkMode.LOOPBACK and (
                workspace.network_policy is NetworkPolicy.OFFLINE
            ):
                raise PermissionError("Workspace network policy denies loopback access")
            return await self._run(
                argv,
                cwd,
                tool.timeout_seconds,
                workspace,
                network=network,
            )
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
        *,
        writable: bool = True,
        network: SandboxNetworkMode = SandboxNetworkMode.OFFLINE,
    ) -> ToolExecutionResult:
        if self.sandbox is None or not self.sandbox.is_available():
            raise SandboxUnavailableError("OS sandbox is unavailable")
        execution_argv = _classify_command(argv, cwd, workspace)
        readable_roots = _sandbox_readable_roots(workspace)
        request = SandboxRequest(
            argv=tuple(execution_argv),
            cwd=str(cwd),
            readable_roots=readable_roots,
            writable_roots=workspace.action_roots if writable else (),
            environment=_sandbox_environment(workspace),
            network=network,
            limits=SandboxLimits(
                wall_time_seconds=timeout_seconds,
                cpu_time_seconds=timeout_seconds,
            ),
        )
        result = await self.sandbox.execute(request)
        stdout = result.stdout[:MAX_OUTPUT_CHARS]
        stderr = result.stderr[:MAX_OUTPUT_CHARS]
        return ToolExecutionResult(
            output={
                "argv": argv,
                "returncode": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": (
                    result.stdout_truncated
                    or result.stderr_truncated
                    or len(result.stdout) > MAX_OUTPUT_CHARS
                    or len(result.stderr) > MAX_OUTPUT_CHARS
                ),
                "sandbox": {
                    "backend": result.backend_id,
                    "network": result.network.value,
                    "duration_ms": result.duration_ms,
                },
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
    if "/" in command:
        executable = _resolve_workspace_executable(command, cwd, workspace)
        return [str(executable), *argv[1:]]

    executable = _resolve_executable(command, workspace)
    if command in PYTHON_COMMANDS:
        if len(argv) == 2 and argv[1] in {"--version", "-V"}:
            return [executable, argv[1]]
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in PYTHON_MODULES:
            return [executable, *argv[1:]]
        if len(argv) >= 2 and not argv[1].startswith("-"):
            script = _resolve_workspace_file(argv[1], cwd, workspace)
            return [executable, str(script), *argv[2:]]
        raise PermissionError("Python accepts only reviewed modules or Workspace scripts")

    if command == "uv":
        if argv == ["uv", "--version"]:
            return [executable, "--version"]
        if (
            len(argv) >= 3
            and argv[1] == "run"
            and not any(
                item == "--with"
                or item == "--with-editable"
                or item.startswith("--with=")
                or item.startswith("--with-editable=")
                for item in argv[2:]
            )
        ):
            return [executable, *argv[1:]]
        raise PermissionError("uv accepts only offline project run commands")

    if command in PACKAGE_SCRIPT_COMMANDS:
        if argv == [command, "--version"]:
            return [executable, "--version"]
        if argv == [command, "test"] or (
            len(argv) >= 3 and argv[1] == "run" and not argv[2].startswith("-")
        ):
            return [executable, *argv[1:]]
        raise PermissionError(f"{command} accepts only existing project scripts")

    if command == "make":
        if argv == ["make", "--version"]:
            return [executable, "--version"]
        targets = {item.lower() for item in argv[1:] if not item.startswith("-")}
        if targets & FORBIDDEN_MAKE_TARGETS:
            raise PermissionError("Make install, release, publish, and deploy targets are denied")
        return [executable, *argv[1:]]

    if command == "cargo":
        if argv == ["cargo", "--version"]:
            return [executable, "--version"]
        if len(argv) >= 2 and argv[1] in CARGO_SUBCOMMANDS:
            return [executable, *argv[1:]]
        raise PermissionError("Cargo command is not a reviewed build or test frontend")

    if command == "node":
        if argv == ["node", "--version"]:
            return [executable, "--version"]
        if len(argv) >= 2 and not argv[1].startswith("-"):
            script = _resolve_workspace_file(argv[1], cwd, workspace)
            return [executable, str(script), *argv[2:]]
        raise PermissionError("Node accepts only Workspace script files")

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
    located = shutil.which(command, path=_sanitized_path(workspace))
    if located is None:
        raise FileNotFoundError(command)
    located_path = Path(located).absolute()
    resolved = located_path.resolve()
    if workspace.allows_action_path(located_path) or workspace.allows_action_path(resolved):
        raise PermissionError(f"Workspace executable {command} is not trusted")
    trusted_roots = _reviewed_toolchain_roots()
    if not any(
        _path_is_within(located_path, root) or _path_is_within(resolved, root)
        for root in trusted_roots
    ):
        raise PermissionError(f"Executable {command} is outside reviewed toolchain roots")
    if command == "make" and located_path == Path("/usr/bin/make"):
        xcode_make = Path("/Library/Developer/CommandLineTools/usr/bin/make")
        if xcode_make.is_file():
            return str(xcode_make)
    return str(located_path)


def _resolve_workspace_executable(command: str, cwd: Path, workspace: Workspace) -> Path:
    candidate = Path(command)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    resolved = candidate.resolve()
    if not workspace.allows_action_path(resolved):
        raise PermissionError("project executable resolves outside the authorized Workspace")
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise PermissionError("project executable is missing, non-regular, or not executable")
    return resolved


def _resolve_workspace_file(value: str, cwd: Path, workspace: Workspace) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    resolved = candidate.resolve()
    if not workspace.allows_action_path(resolved) or not resolved.is_file():
        raise PermissionError("project script resolves outside the authorized Workspace")
    return resolved


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


def _reviewed_toolchain_roots() -> tuple[Path, ...]:
    home = Path.home().resolve()
    candidates = [
        Path("/System"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/Library/Developer"),
        Path("/opt/homebrew"),
        Path("/usr/local"),
        home / ".pyenv",
        home / ".nvm" / "versions",
        home / ".rustup",
        home / ".cargo" / "bin",
        home / ".cargo" / "registry",
        home / ".cargo" / "git",
        home / ".local" / "bin",
        home / "Library" / "pnpm",
    ]
    candidates.extend(_declared_toolchain_roots())
    candidates.extend(_declared_cargo_cache_roots())
    candidates.extend(_toolchain_roots_from_path())
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _declared_toolchain_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for variable, expected_name in (
        ("PYENV_ROOT", ".pyenv"),
        ("RUSTUP_HOME", ".rustup"),
    ):
        value = os.environ.get(variable)
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.is_absolute() and candidate.name == expected_name and candidate.is_dir():
            roots.append(candidate.resolve())
    return tuple(roots)


def _declared_cargo_home() -> Path | None:
    value = os.environ.get("CARGO_HOME")
    candidate = Path(value).expanduser() if value else Path.home() / ".cargo"
    if not candidate.is_absolute() or candidate.name != ".cargo":
        return None
    try:
        return candidate.resolve() if candidate.is_dir() else None
    except OSError:
        return None


def _declared_cargo_cache_roots() -> tuple[Path, ...]:
    cargo_home = _declared_cargo_home()
    if cargo_home is None:
        return ()
    roots: list[Path] = []
    for name in ("bin", "registry", "git"):
        candidate = cargo_home / name
        try:
            if candidate.exists():
                roots.append(candidate.resolve())
        except OSError:
            continue
    return tuple(roots)


def _toolchain_roots_from_path() -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in os.environ.get("PATH", "").split(os.pathsep):
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            continue
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            # A parent process may contribute PATH entries the sandbox deliberately
            # cannot inspect. Those entries are unusable and must not abort discovery.
            continue
        parts = candidate.parts
        for marker, suffix in ((".pyenv", ()), (".nvm", ("versions",))):
            if marker not in parts:
                continue
            marker_index = parts.index(marker)
            end = marker_index + 1 + len(suffix)
            if tuple(parts[marker_index + 1 : end]) != suffix:
                continue
            root = Path(*parts[:end]).resolve()
            if root.is_dir() and root not in roots:
                roots.append(root)
        if len(parts) >= 2 and parts[-2:] == (".cargo", "bin"):
            root = candidate.resolve()
            if root not in roots:
                roots.append(root)
    return tuple(roots)


def _sandbox_readable_roots(workspace: Workspace) -> tuple[str, ...]:
    roots = [Path(root).resolve() for root in workspace.action_roots]
    internal_root = Path(workspace.internal_root).resolve()
    if any(_path_is_within(internal_root, root) for root in roots):
        raise PermissionError("WeatherFlow internal root overlaps a sandbox Workspace root")
    for root in _reviewed_toolchain_roots():
        if root not in roots:
            roots.append(root)
    return tuple(str(root) for root in roots)


def _sandbox_environment(workspace: Workspace) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"LANG", "LC_ALL", "LC_CTYPE", "CI", "TERM", "NO_COLOR"}
    }
    environment["PATH"] = _sanitized_path(workspace)
    declared_roots = {root.name: root for root in _declared_toolchain_roots()}
    pyenv_root = declared_roots.get(".pyenv", Path.home() / ".pyenv")
    if pyenv_root.is_dir():
        environment["PYENV_ROOT"] = str(pyenv_root.resolve())
    rustup_home = declared_roots.get(".rustup", Path.home() / ".rustup")
    if rustup_home.is_dir():
        environment["RUSTUP_HOME"] = str(rustup_home.resolve())
    cargo_home = _declared_cargo_home()
    if cargo_home is not None:
        environment["CARGO_HOME"] = str(cargo_home)
    return environment


def _path_is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or candidate.is_relative_to(root)


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
