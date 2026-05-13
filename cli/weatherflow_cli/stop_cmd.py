"""``wf stop`` — stop dev API + Next.js (PID file from ``wf start`` or listen ports)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from weatherflow_cli.paths import dashboard_port_from_env, load_root_dotenv, project_root

console = Console()

_STATE_DIR_NAME = ".weatherflow"
_PID_FILE = "dev-pids.json"


def _pid_file_path(root: Path) -> Path:
    return root / _STATE_DIR_NAME / _PID_FILE


def _listeners_unix(port: int) -> list[int]:
    r = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return []
    out: list[int] = []
    for line in r.stdout.strip().splitlines():
        try:
            out.append(int(line.strip()))
        except ValueError:
            pass
    return out


def _listeners_windows(port: int) -> list[int]:
    r = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return []
    needle = f":{port}"
    found: list[int] = []
    for line in r.stdout.splitlines():
        if "LISTENING" not in line.upper():
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            found.append(int(parts[-1]))
        except ValueError:
            continue
    return list(dict.fromkeys(found))


def _listeners(port: int) -> list[int]:
    if sys.platform == "win32":
        return _listeners_windows(port)
    return _listeners_unix(port)


def _kill_windows(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
    )


def _signal_stop(pid: int) -> None:
    if sys.platform == "win32":
        _kill_windows(pid)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def _still_alive(pid: int) -> bool:
    if sys.platform == "win32":
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0 and str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _force_kill_unix(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print targets only; do not kill."),
    ports_only: bool = typer.Option(
        False,
        "--ports-only",
        help="Ignore .weatherflow/dev-pids.json; only kill listeners on API + dashboard ports.",
    ),
) -> None:
    load_root_dotenv()
    root = project_root()
    api_port = int(os.environ.get("APP_PORT", "8765"))
    front_port = dashboard_port_from_env()
    me = os.getpid()

    targets: set[int] = set()
    pid_path = _pid_file_path(root)

    if not ports_only and pid_path.is_file():
        try:
            data = json.loads(pid_path.read_text(encoding="utf-8"))
            for key in ("api", "front"):
                v = data.get(key)
                if isinstance(v, int) and v > 0:
                    targets.add(v)
        except (json.JSONDecodeError, OSError):
            pass

    for p in (api_port, front_port):
        for pid in _listeners(p):
            if pid != me:
                targets.add(pid)

    if not targets:
        console.print(
            "[dim]No WeatherFlow dev processes found "
            f"(ports {api_port} / {front_port}).[/dim]"
        )
        if pid_path.is_file() and not dry_run:
            try:
                pid_path.unlink()
            except OSError:
                pass
        raise typer.Exit(0)

    console.print(
        f"[bold]Stopping[/bold] PIDs {sorted(targets)} "
        f"(API :{api_port}, dashboard :{front_port})"
    )
    if dry_run:
        raise typer.Exit(0)

    for pid in sorted(targets):
        _signal_stop(pid)

    time.sleep(1.2)
    for pid in sorted(targets):
        if _still_alive(pid) and sys.platform != "win32":
            _force_kill_unix(pid)

    if pid_path.is_file():
        try:
            pid_path.unlink()
        except OSError:
            pass

    console.print("[green]Done.[/green]")
