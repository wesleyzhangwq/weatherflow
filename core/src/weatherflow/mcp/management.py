from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from weatherflow.capabilities import ToolHealth, ToolSpec
from weatherflow.mcp.catalog import (
    CuratedMCPCatalog,
    MCPPreset,
    MCPPresetUnavailableError,
    UnknownMCPPresetError,
)
from weatherflow.mcp.client import ConnectedMCP, MCPRegistry, MCPTransport, MCPUnavailableError
from weatherflow.mcp.transport import StdioMCPTransport
from weatherflow.runtime import ToolExecutionContext, ToolExecutionResult


class MCPManagedHealth(StrEnum):
    NOT_INSTALLED = "not_installed"
    DISABLED = "disabled"
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


class MCPInstallationError(RuntimeError):
    pass


class MCPNotInstalledError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MCPInstallAuthorization:
    approved_action_id: str


@dataclass(frozen=True, slots=True)
class _PreparedNpmInstall:
    npm: str
    target: Path
    temporary: Path | None
    environment: dict[str, str]


@dataclass(frozen=True, slots=True)
class MCPWorkspaceContext:
    """Trusted context resolved by Python from a Workspace id, never renderer paths."""

    workspace_id: str
    internal_root: Path
    action_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not self.workspace_id.strip():
            raise ValueError("workspace id is required")
        internal_root = self.internal_root.expanduser().resolve()
        action_roots = tuple(path.expanduser().resolve() for path in self.action_roots)
        for root in action_roots:
            if root == internal_root or root.is_relative_to(internal_root):
                raise ValueError("Workspace action root cannot expose the internal root")
        object.__setattr__(self, "internal_root", internal_root)
        object.__setattr__(self, "action_roots", action_roots)


@dataclass(frozen=True, slots=True)
class MCPConnectionState:
    workspace_id: str
    preset_id: str
    preset_version: str
    installed: bool
    enabled: bool
    health: MCPManagedHealth
    tool_ids: tuple[str, ...] = ()
    installed_at: datetime | None = None
    checked_at: datetime | None = None


class MCPConnectionRepository(Protocol):
    async def get(self, workspace_id: str, preset_id: str) -> MCPConnectionState | None: ...

    async def list_for_workspace(self, workspace_id: str) -> tuple[MCPConnectionState, ...]: ...

    async def save(self, state: MCPConnectionState) -> None: ...


class InMemoryMCPConnectionRepository:
    def __init__(self) -> None:
        self._states: dict[tuple[str, str], MCPConnectionState] = {}

    async def get(self, workspace_id: str, preset_id: str) -> MCPConnectionState | None:
        return self._states.get((workspace_id, preset_id))

    async def list_for_workspace(self, workspace_id: str) -> tuple[MCPConnectionState, ...]:
        return tuple(state for key, state in sorted(self._states.items()) if key[0] == workspace_id)

    async def save(self, state: MCPConnectionState) -> None:
        self._states[(state.workspace_id, state.preset_id)] = state


class MCPPresetPackageInstaller(Protocol):
    async def install(
        self,
        preset: MCPPreset,
        *,
        internal_root: Path,
        approved_action_id: str,
    ) -> Path: ...

    def is_installed(self, preset: MCPPreset, *, internal_root: Path) -> bool: ...


class NpmMCPPresetPackageInstaller:
    """Install only catalog-owned npm packages into a private versioned directory."""

    async def install(
        self,
        preset: MCPPreset,
        *,
        internal_root: Path,
        approved_action_id: str,
    ) -> Path:
        if not approved_action_id.strip():
            raise PermissionError("MCP installation requires an approved Action")
        if not preset.available:
            raise MCPPresetUnavailableError(preset.unavailable_reason or preset.preset_id)
        if preset.package_manager != "npm":
            raise MCPInstallationError(f"unsupported installer for preset {preset.preset_id}")
        prepared = await asyncio.to_thread(self._prepare_install, preset, internal_root)
        if prepared.temporary is None:
            return prepared.target
        package_spec = f"{preset.package_name}@{preset.package_version}"
        try:
            process = await asyncio.create_subprocess_exec(
                prepared.npm,
                "install",
                "--prefix",
                str(prepared.temporary),
                "--ignore-scripts",
                "--no-package-lock",
                "--no-audit",
                "--no-fund",
                "--omit=dev",
                "--save=false",
                package_spec,
                cwd=prepared.temporary,
                env=prepared.environment,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await process.wait() != 0:
                raise MCPInstallationError(f"npm install failed for preset {preset.preset_id}")
            await asyncio.to_thread(self._finalize_install, preset, prepared)
        finally:
            await asyncio.to_thread(self._cleanup_temporary, prepared.temporary)
        return prepared.target

    def is_installed(self, preset: MCPPreset, *, internal_root: Path) -> bool:
        internal_root = internal_root.expanduser().resolve()
        target = preset.installation_root(internal_root)
        executable = preset.executable_path(internal_root)
        if self._has_directory_symlink(internal_root, target):
            return False
        return (
            target.resolve().is_relative_to(internal_root)
            and executable.is_file()
            and executable.resolve().is_relative_to(target.resolve())
        )

    def _prepare_install(self, preset: MCPPreset, internal_root: Path) -> _PreparedNpmInstall:
        npm = shutil.which("npm")
        if npm is None:
            raise MCPInstallationError("npm is required to install this MCP preset")
        target = preset.installation_root(internal_root)
        if self.is_installed(preset, internal_root=internal_root):
            return _PreparedNpmInstall(npm=npm, target=target, temporary=None, environment={})
        internal_root = internal_root.expanduser().resolve()
        internal_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        base = self._ensure_private_tree(
            internal_root,
            ("mcp", "servers", preset.preset_id),
        )
        if target.is_symlink():
            raise MCPInstallationError("MCP installation target cannot be a symlink")
        private_home = self._ensure_private_tree(internal_root, ("mcp", "_home"))
        npmrc = private_home / ".npmrc"
        npmrc.touch(mode=0o600, exist_ok=True)
        temporary = base / f".{preset.package_version}.tmp-{uuid4().hex}"
        temporary.mkdir(mode=0o700)
        return _PreparedNpmInstall(
            npm=npm,
            target=target,
            temporary=temporary,
            environment={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(private_home),
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "NPM_CONFIG_USERCONFIG": str(npmrc),
                "NPM_CONFIG_CACHE": str(private_home / ".npm"),
            },
        )

    @staticmethod
    def _finalize_install(preset: MCPPreset, prepared: _PreparedNpmInstall) -> None:
        assert prepared.temporary is not None
        executable = prepared.temporary / "node_modules" / ".bin" / preset.binary_name
        if not executable.is_file() or not executable.resolve().is_relative_to(
            prepared.temporary.resolve()
        ):
            raise MCPInstallationError(
                f"installed preset {preset.preset_id} has no verified executable"
            )
        if prepared.target.exists():
            shutil.rmtree(prepared.target)
        os.replace(prepared.temporary, prepared.target)

    @staticmethod
    def _ensure_private_tree(root: Path, segments: tuple[str, ...]) -> Path:
        current = root
        for segment in segments:
            current = current / segment
            if current.is_symlink():
                raise MCPInstallationError("MCP internal installation path cannot contain symlinks")
            current.mkdir(exist_ok=True, mode=0o700)
            if not current.resolve().is_relative_to(root):
                raise MCPInstallationError("MCP installation escaped the internal root")
        return current

    @staticmethod
    def _has_directory_symlink(root: Path, target: Path) -> bool:
        try:
            relative = target.relative_to(root)
        except ValueError:
            return True
        current = root
        for segment in relative.parts:
            current = current / segment
            if current.is_symlink():
                return True
        return False

    @staticmethod
    def _cleanup_temporary(temporary: Path | None) -> None:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


class WorkspaceRoutedMCPExecutor:
    """Route one canonical MCP tool id to the enabled Workspace connection."""

    def __init__(self, service: MCPManagementService, preset_id: str) -> None:
        self._service = service
        self._preset_id = preset_id

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        connected = self._service.connection(context.workspace_id, self._preset_id)
        if connected is None:
            raise MCPUnavailableError(self._preset_id)
        return await connected.executor.execute(tool, arguments, context)


TransportFactory = Callable[[Sequence[str]], MCPTransport]


class MCPManagementService:
    def __init__(
        self,
        *,
        repository: MCPConnectionRepository,
        package_installer: MCPPresetPackageInstaller | None = None,
        catalog: CuratedMCPCatalog | None = None,
        registry: MCPRegistry | None = None,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self.catalog = catalog or CuratedMCPCatalog.default()
        self.repository = repository
        self.package_installer = package_installer or NpmMCPPresetPackageInstaller()
        self.registry = registry or MCPRegistry()
        self.transport_factory = transport_factory or (lambda argv: StdioMCPTransport(argv))
        self._connections: dict[tuple[str, str], ConnectedMCP] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def install(
        self,
        preset_id: str,
        *,
        workspace: MCPWorkspaceContext,
        authorization: MCPInstallAuthorization,
    ) -> MCPConnectionState:
        preset = self.catalog.require(preset_id)
        if not preset.available:
            raise MCPPresetUnavailableError(preset.unavailable_reason or preset_id)
        if not authorization.approved_action_id.strip():
            raise PermissionError("MCP installation requires an approved Action")
        async with self._lock(workspace.workspace_id, preset_id):
            await self.package_installer.install(
                preset,
                internal_root=workspace.internal_root,
                approved_action_id=authorization.approved_action_id,
            )
            now = datetime.now(UTC)
            previous = await self.repository.get(workspace.workspace_id, preset_id)
            state = MCPConnectionState(
                workspace_id=workspace.workspace_id,
                preset_id=preset_id,
                preset_version=preset.package_version,
                installed=True,
                enabled=False if previous is None else previous.enabled,
                health=(
                    MCPManagedHealth.DISABLED
                    if previous is None or not previous.enabled
                    else previous.health
                ),
                tool_ids=() if previous is None else previous.tool_ids,
                installed_at=now,
                checked_at=now,
            )
            await self.repository.save(state)
            return state

    async def enable(
        self,
        preset_id: str,
        *,
        workspace: MCPWorkspaceContext,
    ) -> MCPConnectionState:
        preset = self.catalog.require(preset_id)
        if not preset.available:
            raise MCPPresetUnavailableError(preset.unavailable_reason or preset_id)
        async with self._lock(workspace.workspace_id, preset_id):
            current = await self.repository.get(workspace.workspace_id, preset_id)
            if (
                current is None
                or not current.installed
                or not self.package_installer.is_installed(
                    preset, internal_root=workspace.internal_root
                )
            ):
                raise MCPNotInstalledError(preset_id)
            await self._close_connection(workspace.workspace_id, preset_id)
            transport = self.transport_factory(
                preset.launch_argv(
                    workspace.internal_root,
                    action_roots=workspace.action_roots,
                )
            )
            try:
                connected = await self.registry.connect(preset_id, transport)
            except (MCPUnavailableError, ConnectionError, OSError, ValueError):
                await transport.close()
                state = replace(
                    current,
                    enabled=True,
                    health=MCPManagedHealth.UNAVAILABLE,
                    tool_ids=(),
                    checked_at=datetime.now(UTC),
                )
                await self.repository.save(state)
                return state
            healthy = bool(connected.tools) and all(
                tool.health is not ToolHealth.UNAVAILABLE for tool in connected.tools
            )
            if healthy:
                self._connections[(workspace.workspace_id, preset_id)] = connected
            else:
                await transport.close()
            state = replace(
                current,
                enabled=True,
                health=(MCPManagedHealth.HEALTHY if healthy else MCPManagedHealth.UNAVAILABLE),
                tool_ids=tuple(tool.tool_id for tool in connected.tools),
                checked_at=datetime.now(UTC),
            )
            await self.repository.save(state)
            return state

    async def disable(self, preset_id: str, *, workspace_id: str) -> MCPConnectionState:
        self.catalog.require(preset_id)
        async with self._lock(workspace_id, preset_id):
            current = await self.repository.get(workspace_id, preset_id)
            if current is None:
                raise MCPNotInstalledError(preset_id)
            await self._close_connection(workspace_id, preset_id)
            state = replace(
                current,
                enabled=False,
                health=MCPManagedHealth.DISABLED,
                tool_ids=(),
                checked_at=datetime.now(UTC),
            )
            await self.repository.save(state)
            return state

    async def health(self, preset_id: str, *, workspace_id: str) -> MCPConnectionState:
        self.catalog.require(preset_id)
        current = await self.repository.get(workspace_id, preset_id)
        if current is None:
            preset = self.catalog.require(preset_id)
            return MCPConnectionState(
                workspace_id=workspace_id,
                preset_id=preset_id,
                preset_version=preset.package_version,
                installed=False,
                enabled=False,
                health=MCPManagedHealth.NOT_INSTALLED,
            )
        connected = self._connections.get((workspace_id, preset_id))
        if not current.enabled or connected is None:
            return current
        try:
            async with asyncio.timeout(5):
                await connected.client.transport.request("ping", {})
        except (MCPUnavailableError, ConnectionError, OSError, TimeoutError):
            await self._close_connection(workspace_id, preset_id)
            current = replace(
                current,
                health=MCPManagedHealth.UNAVAILABLE,
                tool_ids=(),
                checked_at=datetime.now(UTC),
            )
            await self.repository.save(current)
        return current

    async def list_statuses(self, workspace_id: str) -> tuple[MCPConnectionState, ...]:
        persisted = {
            state.preset_id: state
            for state in await self.repository.list_for_workspace(workspace_id)
        }
        return tuple(
            persisted.get(summary.preset_id)
            or MCPConnectionState(
                workspace_id=workspace_id,
                preset_id=summary.preset_id,
                preset_version=summary.version,
                installed=False,
                enabled=False,
                health=MCPManagedHealth.NOT_INSTALLED,
            )
            for summary in self.catalog.summaries()
        )

    async def restore_enabled(
        self, workspace: MCPWorkspaceContext
    ) -> tuple[MCPConnectionState, ...]:
        restored: list[MCPConnectionState] = []
        for state in await self.repository.list_for_workspace(workspace.workspace_id):
            if not state.enabled:
                continue
            try:
                restored.append(await self.enable(state.preset_id, workspace=workspace))
            except (MCPNotInstalledError, MCPPresetUnavailableError, UnknownMCPPresetError):
                unavailable = replace(
                    state,
                    health=MCPManagedHealth.UNAVAILABLE,
                    tool_ids=(),
                    checked_at=datetime.now(UTC),
                )
                await self.repository.save(unavailable)
                restored.append(unavailable)
        return tuple(restored)

    def active_tools(self, workspace_id: str) -> tuple[ToolSpec, ...]:
        tools = (
            tool
            for (connected_workspace_id, _), connected in self._connections.items()
            if connected_workspace_id == workspace_id
            for tool in connected.tools
        )
        return tuple(sorted(tools, key=lambda item: item.tool_id))

    def connection(self, workspace_id: str, preset_id: str) -> ConnectedMCP | None:
        return self._connections.get((workspace_id, preset_id))

    def executor(self, preset_id: str) -> WorkspaceRoutedMCPExecutor:
        self.catalog.require(preset_id)
        return WorkspaceRoutedMCPExecutor(self, preset_id)

    async def close(self) -> None:
        connections = tuple(self._connections.values())
        self._connections.clear()
        for connected in connections:
            await connected.client.transport.close()

    async def _close_connection(self, workspace_id: str, preset_id: str) -> None:
        connected = self._connections.pop((workspace_id, preset_id), None)
        if connected is not None:
            await connected.client.transport.close()

    def _lock(self, workspace_id: str, preset_id: str) -> asyncio.Lock:
        return self._locks.setdefault((workspace_id, preset_id), asyncio.Lock())
