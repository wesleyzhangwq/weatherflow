#!/usr/bin/env python3
"""Run the Tauri development app with the rustup toolchain on PATH."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path


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
        is_this_debug_app = command.endswith(
            "target/debug/weatherflow-desktop"
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
        if "weatherflow serve" not in command or not _process_cwd(pid).startswith(str(root)):
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
    stop_stale_weatherflow_apps()
    cargo = subprocess.run(
        ["rustup", "which", "cargo"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = os.environ.copy()
    environment["PATH"] = f"{Path(cargo).parent}:{environment.get('PATH', '')}"
    development_config = json.dumps(
        {
            "productName": "WeatherFlow Dev",
            "identifier": "ai.weatherflow.desktop.dev",
            "build": {"devUrl": "http://localhost:1421"},
        },
        separators=(",", ":"),
    )
    os.execvpe(
        "pnpm",
        [
            "pnpm",
            "--filter",
            "weatherflow-desktop",
            "exec",
            "tauri",
            "dev",
            "--config",
            development_config,
        ],
        environment,
    )


if __name__ == "__main__":
    main()
