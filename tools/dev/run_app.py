#!/usr/bin/env python3
"""Run the Tauri development app with the rustup toolchain on PATH."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

DEFAULT_DEV_SIGNING_IDENTITY = "WeatherFlow Dev Signer"
COMPATIBLE_DEV_SIGNING_IDENTITIES = (
    DEFAULT_DEV_SIGNING_IDENTITY,
    "OpenHuman Dev Signer",
)
DEVELOPMENT_BUNDLE_IDENTIFIER = "ai.weatherflow.desktop.dev"
WEATHERFLOW_BUNDLE_EXECUTABLE = re.compile(
    r"^/(?:[^/\s]+/)*WeatherFlow(?: Dev)?\.app/Contents/MacOS/"
    r"(?:WeatherFlow(?: Dev)?|weatherflow-desktop)(?:\s|$)"
)
DEVELOPMENT_SIDECAR_INPUTS = (
    Path("core/src/weatherflow"),
    Path("core/pyproject.toml"),
    Path("uv.lock"),
    Path("tools/release/build_sidecar.py"),
)


def available_codesigning_identities() -> set[str]:
    """Return valid local code-signing identity display names."""
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        check=False,
        capture_output=True,
        text=True,
    )
    return set(re.findall(r'^\s*\d+\)\s+[0-9A-F]+\s+"([^"]+)"', result.stdout, re.M))


def resolve_dev_signing_identity() -> str:
    """Select one stable identity without silently falling back to ad-hoc signing."""
    available = available_codesigning_identities()
    override = os.environ.get("WF_DEV_SIGNING_IDENTITY")
    if override:
        if override in available:
            return override
        raise SystemExit(
            f'WF_DEV_SIGNING_IDENTITY names unavailable identity "{override}". '
            "Run `pnpm dev:signing:setup` or choose an identity reported by "
            "`security find-identity -v -p codesigning`."
        )
    for identity in COMPATIBLE_DEV_SIGNING_IDENTITIES:
        if identity in available:
            return identity
    raise SystemExit(
        "WeatherFlow development requires a stable local signing identity. "
        "Run `pnpm dev:signing:setup` once, then retry `pnpm dev:app`."
    )


def cargo_runner_environment_key(environment: dict[str, str]) -> str:
    """Build Cargo's target-specific runner variable for the active toolchain."""
    rustc = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout
    host = next(
        line.removeprefix("host: ")
        for line in rustc.splitlines()
        if line.startswith("host: ")
    )
    return f"CARGO_TARGET_{host.upper().replace('-', '_')}_RUNNER"


def stop_stale_weatherflow_apps() -> None:
    """Replace prior WeatherFlow GUI instances before starting the dev shell."""
    root = Path(__file__).parents[2].resolve()
    processes = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    targets: set[int] = set()
    for process in processes:
        fields = process.strip().split(maxsplit=1)
        if len(fields) != 2:
            continue
        pid_value, command = fields
        executable = command.split(maxsplit=1)[0] if command else ""
        needs_cwd_check = executable.endswith(
            "target/debug/weatherflow-desktop"
        ) or executable.endswith("target/weatherflow-dev-signed/weatherflow-desktop")
        if not is_stale_weatherflow_gui_process(
            command,
            cwd=_process_cwd(int(pid_value)) if needs_cwd_check else "",
            root=root,
        ):
            continue
        targets.add(int(pid_value))
    _terminate_processes(targets)
    stop_stale_development_frontend(root)
    stop_stale_development_daemon(root)


def is_stale_weatherflow_gui_process(command: str, *, cwd: str, root: Path) -> bool:
    """Recognize every packaged or current-worktree WeatherFlow GUI runtime."""
    if WEATHERFLOW_BUNDLE_EXECUTABLE.search(command):
        return True
    executable = command.split(maxsplit=1)[0] if command else ""
    is_current_debug_runtime = executable.endswith(
        "target/debug/weatherflow-desktop"
    ) or executable.endswith("target/weatherflow-dev-signed/weatherflow-desktop")
    root_value = str(root.resolve())
    return (
        is_current_debug_runtime
        and executable.startswith(f"{root_value}{os.sep}")
        and (cwd == root_value or cwd.startswith(f"{root_value}{os.sep}"))
    )


def development_sidecar_stamp(root: Path) -> Path:
    return root / "desktop/src-tauri/target/weatherflow-dev-sidecar-source.sha256"


def development_sidecar_digest(root: Path) -> str:
    """Fingerprint every source input embedded in the development sidecar."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in DEVELOPMENT_SIDECAR_INPUTS:
        candidate = root / relative
        if candidate.is_dir():
            files.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and path.name != ".DS_Store"
            )
        elif candidate.is_file():
            files.append(candidate)
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def development_sidecar_rebuild_required(root: Path) -> bool:
    binary = root / "desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin"
    stamp = development_sidecar_stamp(root)
    if not binary.is_file() or not stamp.is_file():
        return True
    return stamp.read_text().strip() != development_sidecar_digest(root)


def ensure_current_development_sidecar(root: Path) -> None:
    if not development_sidecar_rebuild_required(root):
        print("[weatherflow-dev] Python sidecar matches current Core sources")
        return
    expected_digest = development_sidecar_digest(root)
    print("[weatherflow-dev] Core sources changed; rebuilding Python sidecar")
    subprocess.run(
        [
            "uv",
            "run",
            "--package",
            "weatherflow-core",
            "--extra",
            "release",
            "python",
            "tools/release/build_sidecar.py",
        ],
        cwd=root,
        check=True,
    )
    if development_sidecar_digest(root) != expected_digest:
        raise SystemExit(
            "Core sources changed during the development sidecar build; retry"
        )
    stamp = development_sidecar_stamp(root)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{expected_digest}\n")


def is_stale_development_frontend_process(
    command: str,
    *,
    cwd: str,
    root: Path,
) -> bool:
    """Recognize a Vite listener owned by this checkout or one of its worktrees."""
    root_value = str(root)
    if cwd != root_value and not cwd.startswith(f"{root_value}{os.sep}"):
        return False
    return any(
        marker in command
        for marker in (
            "/vite/bin/vite.js",
            "/.bin/vite",
        )
    )


def stop_stale_development_frontend(root: Path) -> None:
    """Free the dedicated Vite port without touching unrelated local servers."""
    listeners = subprocess.run(
        ["lsof", "-tiTCP:1421", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    targets: set[int] = set()
    for pid_value in listeners:
        if not pid_value.isdigit():
            continue
        pid = int(pid_value)
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
        if not is_stale_development_frontend_process(
            command,
            cwd=_process_cwd(pid),
            root=root,
        ):
            continue
        targets.add(pid)
        parent = _parent_pid(pid)
        if parent is not None and _process_cwd(parent).startswith(str(root)):
            targets.add(parent)
    _terminate_processes(targets)


def stop_stale_development_daemon(root: Path) -> None:
    listeners = subprocess.run(
        ["lsof", "-tiTCP:8765", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    targets: set[int] = set()
    for pid_value in listeners:
        if not pid_value.isdigit():
            continue
        pid = int(pid_value)
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
        if "weatherflow serve" not in command or not _process_cwd(pid).startswith(
            str(root)
        ):
            continue
        targets.add(pid)
        parent = _parent_pid(pid)
        if parent is not None and _process_cwd(parent).startswith(str(root)):
            targets.add(parent)
    _terminate_processes(targets)


def _parent_pid(pid: int) -> int | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "ppid="],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return int(result) if result.isdigit() else None


def _terminate_processes(pids: set[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 1.5
    while pids and time.monotonic() < deadline:
        pids = {pid for pid in pids if _process_exists(pid)}
        if pids:
            time.sleep(0.05)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _process_cwd(pid: int) -> str:
    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    return next(
        (
            line.removeprefix("n")
            for line in result.stdout.splitlines()
            if line.startswith("n")
        ),
        "",
    )


def main() -> None:
    root = Path(__file__).parents[2].resolve()
    stop_stale_weatherflow_apps()
    ensure_current_development_sidecar(root)
    cargo = subprocess.run(
        ["rustup", "which", "cargo"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = os.environ.copy()
    environment["PATH"] = f"{Path(cargo).parent}:{environment.get('PATH', '')}"
    signing_identity = resolve_dev_signing_identity()
    environment["APPLE_SIGNING_IDENTITY"] = signing_identity
    environment["WF_DEV_SIGNING_IDENTITY"] = signing_identity
    environment["WF_DEV_BUNDLE_IDENTIFIER"] = DEVELOPMENT_BUNDLE_IDENTIFIER
    environment[cargo_runner_environment_key(environment)] = str(
        root / "tools" / "dev" / "run_signed_binary.sh"
    )
    development_config = json.dumps(
        {
            "productName": "WeatherFlow Dev",
            "identifier": "ai.weatherflow.desktop.dev",
            "build": {"devUrl": "http://localhost:1421"},
        },
        separators=(",", ":"),
    )
    print(
        "[weatherflow-dev] stable local signing enabled: "
        f'identifier={DEVELOPMENT_BUNDLE_IDENTIFIER} identity="{signing_identity}"'
    )
    command = [
        "pnpm",
        "--filter",
        "weatherflow-desktop",
        "exec",
        "tauri",
        "dev",
        "--config",
        development_config,
    ]
    process = subprocess.Popen(command, env=environment)
    try:
        return_code = process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        stop_stale_development_frontend(root)
        stop_stale_development_daemon(root)
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
