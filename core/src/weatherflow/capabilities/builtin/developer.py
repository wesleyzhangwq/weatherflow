import asyncio
import difflib
import hashlib
import json
import os
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

ALLOWED_COMMANDS = frozenset(
    {"git", "python", "python3", "pytest", "uv", "npm", "npx", "pnpm", "make"}
)
MAX_FILE_BYTES = 1_000_000
MAX_OUTPUT_CHARS = 16_000


def developer_tool_specs() -> tuple[ToolSpec, ...]:
    common = {"source": "builtin.developer", "source_version": "1"}
    return (
        ToolSpec(
            tool_id="developer.read_file",
            description="Read a UTF-8 file inside an authorized Workspace root",
            input_schema={"type": "object", "required": ["path"]},
            output_schema={"type": "object"},
            effect=ToolEffect.OBSERVE,
            required_scopes=frozenset({"workspace:read"}),
            **common,
        ),
        ToolSpec(
            tool_id="developer.write_file",
            description="Atomically write a UTF-8 file with diff and recovery metadata",
            input_schema={"type": "object", "required": ["path", "content"]},
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
                "required": ["name", "media_type", "content"],
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
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            effect=ToolEffect.EXECUTE,
            required_scopes=frozenset({"workspace:execute"}),
            **common,
        ),
        ToolSpec(
            tool_id="developer.run_command",
            description="Run an allowlisted argv command without a shell",
            input_schema={"type": "object", "required": ["argv"]},
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
            return await self._run(["git", "status", "--short"], root, tool.timeout_seconds)
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
            return await self._run(argv, cwd, tool.timeout_seconds)
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

    async def _run(self, argv: list[str], cwd: Path, timeout_seconds: int) -> ToolExecutionResult:
        if argv[0] not in ALLOWED_COMMANDS:
            raise PermissionError(f"command {argv[0]} is not allowlisted")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "CI"}
        }
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
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
