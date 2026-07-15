import asyncio
import os
import sys
from pathlib import Path

import pytest

from weatherflow.sandbox import (
    MacOSSeatbeltSandbox,
    SandboxLimits,
    SandboxNetworkMode,
    SandboxRequest,
    SandboxTimeoutError,
)
from weatherflow.sandbox.macos import _prepare_private_cargo_home, _sandbox_environment

MACOS_SANDBOX_INTEGRATION_UNAVAILABLE = sys.platform != "darwin" or bool(
    os.environ.get("WF_SANDBOX_ACTIVE")
)


def request(
    workspace: Path,
    argv: tuple[str, ...],
    *,
    writable: bool = True,
    wall_time_seconds: float = 5,
    network: SandboxNetworkMode = SandboxNetworkMode.OFFLINE,
) -> SandboxRequest:
    return SandboxRequest(
        argv=argv,
        cwd=str(workspace),
        readable_roots=(str(workspace),),
        writable_roots=(str(workspace),) if writable else (),
        environment={"PATH": "/usr/bin:/bin"},
        network=network,
        limits=SandboxLimits(wall_time_seconds=wall_time_seconds),
    )


def test_request_requires_cwd_and_writable_roots_to_be_scoped(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="working directory"):
        SandboxRequest(
            argv=("/bin/echo", "hello"),
            cwd=str(outside),
            readable_roots=(str(workspace),),
        )

    with pytest.raises(ValueError, match="writable root"):
        SandboxRequest(
            argv=("/bin/echo", "hello"),
            cwd=str(workspace),
            readable_roots=(str(workspace),),
            writable_roots=(str(outside),),
        )


def test_profile_is_default_deny_and_uses_parameters_for_untrusted_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / 'project "quoted"'
    workspace.mkdir()
    backend = MacOSSeatbeltSandbox()

    profile, parameters = backend.compile_profile(request(workspace, ("/bin/echo", "ok")))

    assert "(deny default)" in profile
    assert "(remote ip" not in profile
    assert "(local ip" not in profile
    assert str(workspace) not in profile
    assert str(workspace.resolve()) in parameters.values()
    assert "(allow signal (target self))" in profile
    assert "(allow signal (target children))" in profile
    assert "(allow signal)" not in profile
    assert "SYS_setsid" in profile
    assert "SYS_setpgid" in profile

    loopback, _ = backend.compile_profile(
        request(
            workspace,
            ("/bin/echo", "ok"),
            network=SandboxNetworkMode.LOOPBACK,
        )
    )
    assert '(remote ip "localhost:*")' in loopback
    assert '(local ip "localhost:*")' in loopback

    https_egress, _ = backend.compile_profile(
        request(
            workspace,
            ("/bin/echo", "ok"),
            network=SandboxNetworkMode.HTTPS_EGRESS,
        )
    )
    assert '(remote tcp "*:443")' in https_egress
    assert '(remote ip "localhost:*")' in https_egress
    assert "(local ip" not in https_egress


def test_backend_marks_the_child_environment_without_inheriting_a_parent_marker() -> None:
    environment = _sandbox_environment(
        {"PATH": "/usr/bin:/bin"},
        "/tmp/weatherflow-test-home",
    )

    assert environment["WF_SANDBOX_ACTIVE"] == "macos-seatbelt-v1"


async def test_health_probe_fails_closed_when_backend_files_are_missing(tmp_path: Path) -> None:
    backend = MacOSSeatbeltSandbox(
        executable=tmp_path / "missing-sandbox-exec",
        dyld_profile=tmp_path / "missing-profile",
    )

    assert await backend.health_probe() is False


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_health_probe_executes_a_real_escape_denial_check() -> None:
    assert await MacOSSeatbeltSandbox().health_probe() is True


def test_private_cargo_home_reuses_only_reviewed_nonsecret_caches(tmp_path: Path) -> None:
    source_home = tmp_path / "host" / ".cargo"
    registry = source_home / "registry"
    git = source_home / "git"
    registry.mkdir(parents=True)
    git.mkdir()
    (registry / "marker").write_text("cached")
    (source_home / "credentials.toml").write_text("secret")
    sandbox_home = tmp_path / "sandbox-home"
    sandbox_home.mkdir()

    cargo_home = _prepare_private_cargo_home(
        {"CARGO_HOME": str(source_home)},
        str(sandbox_home),
        (str(registry), str(git)),
    )
    environment = _sandbox_environment(
        {"PATH": "/usr/bin:/bin"},
        str(sandbox_home),
        cargo_home=cargo_home,
    )

    private_home = Path(cargo_home)
    assert (private_home / "registry").is_symlink()
    assert (private_home / "git").is_symlink()
    assert (private_home / "registry" / "marker").read_text() == "cached"
    assert not (private_home / "credentials.toml").exists()
    assert environment["CARGO_HOME"] == str(private_home)
    assert environment["CARGO_NET_OFFLINE"] == "true"


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_workspace_script_can_build_but_cannot_read_or_write_outside(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_secret = tmp_path / "secret.txt"
    outside_secret.write_text("host-secret\n")
    script = workspace / "build.sh"
    script.write_text(
        "#!/bin/sh\n"
        "printf 'built\\n' > build.txt\n"
        'if cat "$1" >/dev/null 2>&1; then exit 91; fi\n'
        'if touch "$2" >/dev/null 2>&1; then exit 92; fi\n'
    )
    script.chmod(0o755)
    outside_write = tmp_path / "escaped.txt"

    result = await MacOSSeatbeltSandbox().execute(
        request(
            workspace,
            (str(script), str(outside_secret), str(outside_write)),
        )
    )

    assert result.returncode == 0
    assert (workspace / "build.txt").read_text() == "built\n"
    assert not outside_write.exists()


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_network_and_parent_process_signals_are_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    accepted = asyncio.Event()

    async def accept_connection(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        accepted.set()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(accept_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    probe = workspace / "probe.py"
    probe.write_text(
        "import os, signal, socket, sys\n"
        "network_denied = False\n"
        "signal_denied = False\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.2)\n"
        "except OSError:\n"
        "    network_denied = True\n"
        "try:\n"
        "    os.kill(os.getppid(), 0)\n"
        "except OSError:\n"
        "    signal_denied = True\n"
        "raise SystemExit(0 if network_denied and signal_denied else 1)\n"
    )
    python = Path(await asyncio.to_thread(os.path.realpath, sys.executable))
    toolchain_root = python.parent.parent
    sandbox_request = request(workspace, (str(python), str(probe), str(port)))
    sandbox_request = sandbox_request.model_copy(
        update={"readable_roots": (*sandbox_request.readable_roots, str(toolchain_root))}
    )
    try:
        result = await MacOSSeatbeltSandbox().execute(sandbox_request)
    finally:
        server.close()
        await server.wait_closed()

    assert result.returncode == 0
    assert not accepted.is_set()


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_user_keychain_search_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await MacOSSeatbeltSandbox().execute(
        request(
            workspace,
            ("/usr/bin/security", "list-keychains"),
            writable=False,
        )
    )

    assert result.returncode != 0
    assert not result.stdout.strip()


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_loopback_mode_reaches_local_services_but_not_external_network(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    accepted = asyncio.Event()

    async def accept_connection(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        accepted.set()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(accept_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    probe = workspace / "loopback.py"
    probe.write_text(
        "import socket, sys\n"
        "local_ok = False\n"
        "external_denied = False\n"
        "try:\n"
        "    connection = socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.5)\n"
        "    connection.close()\n"
        "    local_ok = True\n"
        "except OSError:\n"
        "    pass\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=0.2)\n"
        "except OSError:\n"
        "    external_denied = True\n"
        "raise SystemExit(0 if local_ok and external_denied else 1)\n"
    )
    python = Path(await asyncio.to_thread(os.path.realpath, sys.executable))
    sandbox_request = request(
        workspace,
        (str(python), str(probe), str(port)),
        network=SandboxNetworkMode.LOOPBACK,
    )
    sandbox_request = sandbox_request.model_copy(
        update={
            "readable_roots": (
                *sandbox_request.readable_roots,
                str(python.parent.parent),
            )
        }
    )
    try:
        result = await MacOSSeatbeltSandbox().execute(sandbox_request)
        await asyncio.wait_for(accepted.wait(), timeout=1)
    finally:
        server.close()
        await server.wait_closed()

    assert result.returncode == 0


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_https_egress_profile_compiles_without_admitting_loopback(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await MacOSSeatbeltSandbox().execute(
        request(
            workspace,
            ("/bin/echo", "ready"),
            writable=False,
            network=SandboxNetworkMode.HTTPS_EGRESS,
        )
    )

    assert result.returncode == 0
    assert result.stdout == "ready\n"


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_long_lived_stdio_process_uses_the_same_sandbox_boundary(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = workspace / "server.py"
    server.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    print(json.dumps({'id': request['id'], 'sandbox': True}), flush=True)\n"
    )
    python = Path(await asyncio.to_thread(os.path.realpath, sys.executable))
    sandbox_request = request(workspace, (str(python), str(server)), writable=False)
    sandbox_request = sandbox_request.model_copy(
        update={
            "readable_roots": (
                *sandbox_request.readable_roots,
                str(python.parent.parent),
            )
        }
    )

    process = await MacOSSeatbeltSandbox().spawn_stdio(sandbox_request)
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(b'{"id":7}\n')
        await process.stdin.drain()
        response = await asyncio.wait_for(process.stdout.readline(), timeout=1)
    finally:
        await process.close()

    assert response == b'{"id": 7, "sandbox": true}\n'
    assert process.returncode is not None


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_private_unix_sockets_and_owned_child_signals_are_allowed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    probe = workspace / "ipc.py"
    probe.write_text(
        "import os, signal, socket, subprocess\n"
        "path = os.path.join(os.environ['HOME'], 'private.sock')\n"
        "server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "server.bind(path)\n"
        "server.listen(1)\n"
        "client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "client.connect(path)\n"
        "connection, _ = server.accept()\n"
        "connection.close(); client.close(); server.close()\n"
        "child = subprocess.Popen(['/bin/sleep', '10'])\n"
        "child.terminate(); child.wait(timeout=1)\n"
        "parent_denied = False\n"
        "try:\n"
        "    os.kill(os.getppid(), 0)\n"
        "except OSError:\n"
        "    parent_denied = True\n"
        "raise SystemExit(0 if child.returncode == -signal.SIGTERM and parent_denied else 1)\n"
    )
    python = Path(await asyncio.to_thread(os.path.realpath, sys.executable))
    sandbox_request = request(workspace, (str(python), str(probe)))
    sandbox_request = sandbox_request.model_copy(
        update={
            "readable_roots": (
                *sandbox_request.readable_roots,
                str(python.parent.parent),
            )
        }
    )

    result = await MacOSSeatbeltSandbox().execute(sandbox_request)

    assert result.returncode == 0


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_descendants_cannot_escape_the_owned_process_group(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    probe = workspace / "session.py"
    probe.write_text(
        "import subprocess\n"
        "try:\n"
        "    child = subprocess.Popen(['/bin/sleep', '1'], start_new_session=True)\n"
        "except PermissionError:\n"
        "    raise SystemExit(0)\n"
        "child.terminate(); child.wait()\n"
        "raise SystemExit(1)\n"
    )
    python = Path(await asyncio.to_thread(os.path.realpath, sys.executable))
    sandbox_request = request(workspace, (str(python), str(probe)), writable=False)
    sandbox_request = sandbox_request.model_copy(
        update={
            "readable_roots": (
                *sandbox_request.readable_roots,
                str(python.parent.parent),
            )
        }
    )

    result = await MacOSSeatbeltSandbox().execute(sandbox_request)

    assert result.returncode == 0


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_resource_launcher_never_interpolates_project_arguments(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    injected = workspace / "injected.txt"
    literal = f"$(touch {injected})"

    result = await MacOSSeatbeltSandbox().execute(
        request(workspace, ("/bin/echo", literal), writable=True)
    )

    assert result.returncode == 0
    assert result.stdout == literal + "\n"
    assert not injected.exists()


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_timeout_kills_the_sandbox_process_group(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    delayed_write = workspace / "must-not-exist.txt"
    script = workspace / "slow.sh"
    script.write_text('#!/bin/sh\n(sleep 1; printf escaped > "$1") &\nsleep 10\n')
    script.chmod(0o755)

    with pytest.raises(SandboxTimeoutError):
        await MacOSSeatbeltSandbox().execute(
            request(
                workspace,
                (str(script), str(delayed_write)),
                wall_time_seconds=0.1,
            )
        )
    await asyncio.sleep(1.1)

    assert not delayed_write.exists()


@pytest.mark.skipif(
    MACOS_SANDBOX_INTEGRATION_UNAVAILABLE,
    reason="macOS Seatbelt integration cannot be nested",
)
async def test_parent_environment_is_not_inherited(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WF_SANDBOX_MUST_NOT_LEAK", "secret-value")

    result = await MacOSSeatbeltSandbox().execute(
        request(workspace, ("/usr/bin/env",), writable=False)
    )

    assert "WF_SANDBOX_MUST_NOT_LEAK" not in result.stdout
    assert "secret-value" not in result.stdout
    assert "HOME=" in result.stdout
