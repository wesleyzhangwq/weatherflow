from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from weatherflow.mcp import (
    CuratedMCPCatalog,
    CuratedMCPPresetPackageInstaller,
    InMemoryMCPConnectionRepository,
    MCPInstallationError,
    MCPInstallAuthorization,
    MCPManagedHealth,
    MCPManagementService,
    MCPPresetUnavailableError,
    MCPWorkspaceContext,
    NpmMCPPresetPackageInstaller,
    UnknownMCPPresetError,
)
from weatherflow.sandbox import SandboxNetworkMode, SandboxResult


class FakeTransport:
    def __init__(self, *, tool_name: str = "read_text_file") -> None:
        self.closed = False
        self.tool_name = tool_name

    async def request(self, method, params=None):
        if method == "initialize":
            return {"serverInfo": {"name": "fixture", "version": "1.2.3"}}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": self.tool_name,
                        "description": "Read one authorized file",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            }
        if method == "ping":
            return {}
        raise AssertionError(method)

    async def close(self) -> None:
        self.closed = True


class FakePackageInstaller:
    def __init__(self) -> None:
        self.installed: list[tuple[str, Path, str]] = []

    async def install(self, preset, *, internal_root: Path, approved_action_id: str) -> Path:
        target = preset.installation_root(internal_root)
        executable = preset.executable_path(internal_root)
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("fixture")
        self.installed.append((preset.preset_id, target, approved_action_id))
        return target

    def is_installed(self, preset, *, internal_root: Path) -> bool:
        return preset.executable_path(internal_root).is_file()


class RecordingInstallSandbox:
    def __init__(self) -> None:
        self.requests = []

    @property
    def backend_id(self) -> str:
        return "recording-sandbox"

    def is_available(self) -> bool:
        return True

    async def execute(self, request):
        self.requests.append(request)
        binary_name = (
            "mcp-server-memory"
            if request.argv[-1].startswith("@modelcontextprotocol/server-memory@")
            else "mcp-server-filesystem"
        )
        executable = Path(request.cwd) / "node_modules" / ".bin" / binary_name
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture")
        return SandboxResult(
            backend_id=self.backend_id,
            argv=request.argv,
            returncode=0,
            stdout="",
            stderr="",
            duration_ms=1,
            network=request.network,
        )


class InteractiveStdioProcess:
    def __init__(self, *, tool_name: str = "read_text_file") -> None:
        self.stdout = asyncio.StreamReader()
        self.stdin = InteractiveStdin(self.stdout, tool_name=tool_name)
        self.returncode = None
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.returncode = 0
        self.stdout.feed_eof()


class InteractiveStdin:
    def __init__(self, stdout: asyncio.StreamReader, *, tool_name: str) -> None:
        self.stdout = stdout
        self.tool_name = tool_name

    def write(self, value: bytes) -> None:
        payload = json.loads(value)
        if "id" not in payload:
            return
        if payload["method"] == "initialize":
            result = {"serverInfo": {"name": "sandboxed", "version": "1"}}
        elif payload["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": self.tool_name,
                        "description": "Read one file",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            }
        else:
            result = {}
        response = {"jsonrpc": "2.0", "id": payload["id"], "result": result}
        self.stdout.feed_data((json.dumps(response) + "\n").encode())

    async def drain(self) -> None:
        return None


class RecordingStdioSandbox:
    def __init__(self, *, tool_name: str = "read_text_file") -> None:
        self.requests = []
        self.processes = []
        self.tool_name = tool_name

    @property
    def backend_id(self) -> str:
        return "recording-stdio-sandbox"

    def is_available(self) -> bool:
        return True

    async def execute(self, request):
        raise AssertionError("long-lived MCP must use spawn_stdio")

    async def spawn_stdio(self, request):
        self.requests.append(request)
        process = InteractiveStdioProcess(tool_name=self.tool_name)
        self.processes.append(process)
        return process


def workspace_context(tmp_path: Path) -> MCPWorkspaceContext:
    project = tmp_path / "project"
    project.mkdir()
    return MCPWorkspaceContext(
        workspace_id="workspace-1",
        internal_root=tmp_path / "internal",
        action_roots=(project,),
    )


def test_catalog_is_fixed_version_pinned_and_renderer_safe() -> None:
    catalog = CuratedMCPCatalog.default()

    assert {item.preset_id for item in catalog.summaries()} == {
        "filesystem",
        "git-readonly",
        "memory",
        "time",
    }
    assert catalog.require("filesystem").package_version == "2026.7.10"
    assert catalog.require("memory").package_version == "2026.7.4"
    assert catalog.require("memory").available is True
    assert catalog.require("memory").state_filename == "memory.jsonl"
    assert "read_graph" in catalog.require("memory").allowed_tool_names
    assert "read_file" in catalog.require("filesystem").allowed_tool_names
    assert catalog.require("playwright").package_version == "0.0.78"
    assert catalog.require("playwright").available is False
    assert catalog.require("fetch").available is False
    assert catalog.require("time").available is True
    assert catalog.require("git-readonly").available is True
    assert catalog.require("context7").available is False
    assert "private" in (catalog.require("fetch").unavailable_reason or "").lower()

    public = catalog.require("filesystem").to_summary().model_dump()
    assert "package_name" not in public
    assert "binary_name" not in public
    assert "argv" not in public

    with pytest.raises(UnknownMCPPresetError):
        catalog.require("npx --yes attacker-package")


async def test_install_requires_approved_action_and_stays_under_internal_root(
    tmp_path: Path,
) -> None:
    installer = FakePackageInstaller()
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=installer,
        transport_factory=lambda argv: FakeTransport(),
    )
    workspace = workspace_context(tmp_path)

    with pytest.raises(PermissionError, match="approved Action"):
        await service.install(
            "filesystem",
            workspace=workspace,
            authorization=MCPInstallAuthorization(approved_action_id=""),
        )

    installed = await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    assert installed.installed is True
    assert installed.enabled is False
    _, target, action_id = installer.installed[0]
    assert target.is_relative_to(workspace.internal_root.resolve())
    assert action_id == "action-1"


async def test_fetch_is_visible_but_cannot_be_installed_without_ssrf_boundary(
    tmp_path: Path,
) -> None:
    installer = FakePackageInstaller()
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=installer,
        transport_factory=lambda argv: FakeTransport(),
    )

    with pytest.raises(MCPPresetUnavailableError, match="private"):
        await service.install(
            "fetch",
            workspace=workspace_context(tmp_path),
            authorization=MCPInstallAuthorization(approved_action_id="action-1"),
        )

    assert installer.installed == []


async def test_enable_uses_fixed_filesystem_argv_and_disable_closes_transport(
    tmp_path: Path,
) -> None:
    transports: list[tuple[tuple[str, ...], FakeTransport]] = []

    def transport_factory(argv):
        transport = FakeTransport()
        transports.append((tuple(argv), transport))
        return transport

    repository = InMemoryMCPConnectionRepository()
    service = MCPManagementService(
        repository=repository,
        package_installer=FakePackageInstaller(),
        transport_factory=transport_factory,
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    status = await service.enable("filesystem", workspace=workspace)

    argv, transport = transports[0]
    assert argv[0] == str(
        CuratedMCPCatalog.default().require("filesystem").executable_path(workspace.internal_root)
    )
    assert argv[1:] == tuple(str(path.resolve()) for path in workspace.action_roots)
    assert status.enabled is True
    assert status.health is MCPManagedHealth.HEALTHY
    assert [tool.tool_id for tool in service.active_tools(workspace.workspace_id)] == [
        "mcp.filesystem.read_text_file"
    ]

    disabled = await service.disable("filesystem", workspace_id=workspace.workspace_id)

    assert disabled.enabled is False
    assert disabled.health is MCPManagedHealth.DISABLED
    assert transport.closed is True
    assert service.active_tools(workspace.workspace_id) == ()


async def test_default_stdio_server_is_offline_and_read_only_inside_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "node-runtime"
    (runtime / "bin").mkdir(parents=True)
    monkeypatch.setattr(
        NpmMCPPresetPackageInstaller,
        "_resolve_node_runtime",
        staticmethod(lambda: (str(runtime / "bin" / "npm"), runtime)),
    )
    sandbox = RecordingStdioSandbox()
    repository = InMemoryMCPConnectionRepository()
    service = MCPManagementService(
        repository=repository,
        package_installer=FakePackageInstaller(),
        sandbox=sandbox,
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    enabled = await service.enable("filesystem", workspace=workspace)
    await service.disable("filesystem", workspace_id=workspace.workspace_id)

    assert enabled.health is MCPManagedHealth.HEALTHY
    assert len(sandbox.requests) == 1
    request = sandbox.requests[0]
    preset = CuratedMCPCatalog.default().require("filesystem")
    assert request.cwd == str(preset.installation_root(workspace.internal_root))
    assert request.readable_roots == (
        str(preset.installation_root(workspace.internal_root)),
        *(str(path) for path in workspace.action_roots),
        str(runtime),
    )
    assert request.writable_roots == ()
    assert request.environment["PATH"].split(":", 1)[0] == str(runtime / "bin")
    assert request.network is SandboxNetworkMode.OFFLINE
    assert sandbox.processes[0].closed is True


async def test_memory_stdio_server_gets_only_private_state_write_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "node-runtime"
    (runtime / "bin").mkdir(parents=True)
    monkeypatch.setattr(
        NpmMCPPresetPackageInstaller,
        "_resolve_node_runtime",
        staticmethod(lambda: (str(runtime / "bin" / "npm"), runtime)),
    )
    sandbox = RecordingStdioSandbox(tool_name="read_graph")
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=FakePackageInstaller(),
        sandbox=sandbox,
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "memory",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    enabled = await service.enable("memory", workspace=workspace)

    assert enabled.health is MCPManagedHealth.HEALTHY
    request = sandbox.requests[0]
    preset = CuratedMCPCatalog.default().require("memory")
    state_root = preset.state_root(workspace.internal_root)
    assert request.cwd == str(state_root)
    assert request.readable_roots == (
        str(preset.installation_root(workspace.internal_root)),
        str(state_root),
        str(runtime),
    )
    assert request.writable_roots == (str(state_root),)
    assert request.environment["MEMORY_FILE_PATH"] == str(state_root / "memory.jsonl")
    assert str(workspace.action_roots[0]) not in request.readable_roots
    assert request.network is SandboxNetworkMode.OFFLINE


async def test_builtin_presets_install_without_a_host_package_manager(
    tmp_path: Path,
) -> None:
    installer = CuratedMCPPresetPackageInstaller()
    preset = CuratedMCPCatalog.default().require("time")

    installed = await installer.install(
        preset,
        internal_root=tmp_path / "internal",
        approved_action_id="action-1",
    )

    assert installed == preset.installation_root(tmp_path / "internal")
    assert installer.is_installed(preset, internal_root=tmp_path / "internal")
    assert preset.executable_path(tmp_path / "internal").read_text() == "weatherflow-builtin-mcp\n"


async def test_preset_tool_allowlist_fails_closed_on_unexpected_discovery(
    tmp_path: Path,
) -> None:
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=FakePackageInstaller(),
        transport_factory=lambda argv: FakeTransport(tool_name="surprise_write"),
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    enabled = await service.enable("filesystem", workspace=workspace)

    assert enabled.health is MCPManagedHealth.UNAVAILABLE
    assert enabled.tool_ids == ()
    assert service.active_tools(workspace.workspace_id) == ()


async def test_memory_state_reset_counts_deletes_and_restarts_enabled_server(
    tmp_path: Path,
) -> None:
    transports: list[FakeTransport] = []

    def transport_factory(argv):
        transport = FakeTransport(tool_name="read_graph")
        transports.append(transport)
        return transport

    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=FakePackageInstaller(),
        transport_factory=transport_factory,
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "memory",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )
    await service.enable("memory", workspace=workspace)
    preset = CuratedMCPCatalog.default().require("memory")
    state_root = preset.state_root(workspace.internal_root)
    state_root.mkdir(parents=True, exist_ok=True)
    state_file = state_root / "memory.jsonl"
    state_file.write_text('{"type":"entity"}\n{"type":"relation"}\n')

    assert await service.persistent_state_count("memory", workspace=workspace) == 2
    deleted = await service.reset_persistent_state("memory", workspace=workspace)

    assert deleted == 2
    assert not state_file.exists()
    assert transports[0].closed is True
    assert len(transports) == 2
    assert service.connection(workspace.workspace_id, "memory") is not None


async def test_memory_state_reset_deletes_malformed_private_state(
    tmp_path: Path,
) -> None:
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=FakePackageInstaller(),
        transport_factory=lambda argv: FakeTransport(tool_name="read_graph"),
    )
    workspace = workspace_context(tmp_path)
    preset = CuratedMCPCatalog.default().require("memory")
    state_file = preset.state_root(workspace.internal_root) / "memory.jsonl"
    state_file.parent.mkdir(parents=True)
    state_file.write_bytes(b"\xff\n")

    deleted = await service.reset_persistent_state("memory", workspace=workspace)

    assert deleted == 1
    assert not state_file.exists()


async def test_missing_stdio_sandbox_marks_managed_server_unavailable(
    tmp_path: Path,
) -> None:
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=FakePackageInstaller(),
    )
    workspace = workspace_context(tmp_path)
    await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )

    enabled = await service.enable("filesystem", workspace=workspace)

    assert enabled.health is MCPManagedHealth.UNAVAILABLE
    assert enabled.tool_ids == ()


def test_playwright_safe_arguments_are_fixed_by_catalog() -> None:
    preset = CuratedMCPCatalog.default().require("playwright")

    assert preset.fixed_arguments == (
        "--headless",
        "--isolated",
        "--sandbox",
        "--block-service-workers",
        "--image-responses=omit",
        "--output-mode=stdout",
        "--browser=chrome",
    )
    assert "redirect-safe" in (preset.unavailable_reason or "")


async def test_enabled_connections_restore_without_reinstall_or_new_approval(
    tmp_path: Path,
) -> None:
    repository = InMemoryMCPConnectionRepository()
    installer = FakePackageInstaller()
    workspace = workspace_context(tmp_path)
    first = MCPManagementService(
        repository=repository,
        package_installer=installer,
        transport_factory=lambda argv: FakeTransport(),
    )
    await first.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-1"),
    )
    await first.enable("filesystem", workspace=workspace)
    await first.close()

    restored_service = MCPManagementService(
        repository=repository,
        package_installer=installer,
        transport_factory=lambda argv: FakeTransport(),
    )
    restored = await restored_service.restore_enabled(workspace)

    assert len(installer.installed) == 1
    assert restored[0].health is MCPManagedHealth.HEALTHY
    assert restored_service.active_tools(workspace.workspace_id)


def test_workspace_context_rejects_internal_root_as_filesystem_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="internal root"):
        MCPWorkspaceContext(
            workspace_id="workspace-1",
            internal_root=tmp_path / "internal",
            action_roots=(tmp_path / "internal" / "nested",),
        )


async def test_npm_installer_rejects_internal_symlink_escape(tmp_path: Path) -> None:
    internal = tmp_path / "internal"
    outside = tmp_path / "outside"
    internal.mkdir()
    outside.mkdir()
    (internal / "mcp").symlink_to(outside, target_is_directory=True)

    with pytest.raises(MCPInstallationError, match="symlink"):
        await NpmMCPPresetPackageInstaller().install(
            CuratedMCPCatalog.default().require("filesystem"),
            internal_root=internal,
            approved_action_id="action-1",
        )


async def test_npm_installer_executes_only_through_dedicated_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = RecordingInstallSandbox()
    monkeypatch.setattr(
        "weatherflow.mcp.management.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    internal = tmp_path / "internal"

    installed = await NpmMCPPresetPackageInstaller(sandbox=sandbox).install(
        CuratedMCPCatalog.default().require("filesystem"),
        internal_root=internal,
        approved_action_id="action-1",
    )

    assert installed.is_relative_to(internal.resolve())
    assert len(sandbox.requests) == 1
    request = sandbox.requests[0]
    assert request.argv[0] == "/usr/bin/npm"
    assert request.argv[1] == "install"
    assert request.network is SandboxNetworkMode.HTTPS_EGRESS
    assert request.writable_roots == (request.cwd,)
    assert request.readable_roots == (request.cwd, "/usr")
    assert str(internal.resolve()) not in request.readable_roots


async def test_npm_installer_scopes_a_user_managed_node_runtime_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "node-runtime"
    bin_root = runtime / "bin"
    npm_module = runtime / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    npm_module.parent.mkdir(parents=True)
    npm_module.write_text("#!/usr/bin/env node\n")
    bin_root.mkdir()
    (bin_root / "node").write_text("node")
    (bin_root / "npm").symlink_to(npm_module)
    monkeypatch.setattr(
        "weatherflow.mcp.management.shutil.which",
        lambda name: str(bin_root / name),
    )
    sandbox = RecordingInstallSandbox()
    internal = tmp_path / "internal"

    await NpmMCPPresetPackageInstaller(sandbox=sandbox).install(
        CuratedMCPCatalog.default().require("memory"),
        internal_root=internal,
        approved_action_id="action-1",
    )

    request = sandbox.requests[0]
    assert request.readable_roots == (request.cwd, str(runtime.resolve()))
    assert request.writable_roots == (request.cwd,)
    assert request.environment["PATH"].split(":", 1)[0] == str(bin_root)


async def test_npm_installer_uses_the_pinned_official_memory_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = RecordingInstallSandbox()
    monkeypatch.setattr(
        "weatherflow.mcp.management.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    internal = tmp_path / "internal"
    preset = CuratedMCPCatalog.default().require("memory")

    installed = await NpmMCPPresetPackageInstaller(sandbox=sandbox).install(
        preset,
        internal_root=internal,
        approved_action_id="action-1",
    )

    assert installed == preset.installation_root(internal)
    request = sandbox.requests[0]
    assert request.argv[-1] == "@modelcontextprotocol/server-memory@2026.7.4"
    assert "--ignore-scripts" in request.argv
    assert preset.executable_path(internal).is_file()
