#!/usr/bin/env python3
"""Run the Tauri development app with the rustup toolchain on PATH."""

from __future__ import annotations

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
    stopped = False
    for process in processes:
        fields = process.strip().split(maxsplit=1)
        if len(fields) != 2:
            continue
        pid_value, command = fields
        is_release = "WeatherFlow.app/Contents/MacOS/weatherflow-desktop" in command
        is_this_debug_app = (
            command.endswith("target/debug/weatherflow-desktop")
            or command.endswith("target/weatherflow-dev-signed/weatherflow-desktop")
        ) and str(root) in _process_cwd(int(pid_value))
        if not (is_release or is_this_debug_app):
            continue
        try:
            os.kill(int(pid_value), signal.SIGTERM)
            stopped = True
        except ProcessLookupError:
            pass
    if stopped:
        time.sleep(0.5)
    stop_stale_development_daemon(root)


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
        stop_stale_development_daemon(root)
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
