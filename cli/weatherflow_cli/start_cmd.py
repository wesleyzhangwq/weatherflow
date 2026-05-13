"""``wf start`` — FastAPI + Next.js dev server (or API only with ``--api-only``)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from weatherflow_cli.paths import dashboard_port_from_env, load_root_dotenv, project_root

console = Console()


def _uvicorn_prefix(backend: Path) -> list[str]:
    if sys.platform == "win32":
        exe = backend / ".venv" / "Scripts" / "uvicorn.exe"
    else:
        exe = backend / ".venv" / "bin" / "uvicorn"
    if exe.is_file():
        return [str(exe)]
    return [sys.executable, "-m", "uvicorn"]


def _popen_kwargs(*, detach: bool) -> dict:
    if sys.platform == "win32":
        if detach:
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {}
    return {"start_new_session": True}


def _terminate_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform != "win32" and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    else:
        proc.terminate()


def _reap(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform != "win32" and proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
        else:
            proc.kill()


def run(
    reload: bool = typer.Option(True, "--reload/--no-reload", help="API hot-reload on code changes."),
    api_only: bool = typer.Option(
        False,
        "--api-only",
        help="Start only FastAPI (legacy single-process mode).",
    ),
    detach: bool = typer.Option(
        False,
        "--detach",
        "--background",
        "-d",
        help="Run in background: free this terminal; logs under .weatherflow/; stop with wf stop.",
    ),
    host: str = typer.Option(
        "",
        "--host",
        help="API bind host (default: APP_HOST from .env or 127.0.0.1).",
    ),
    port: int = typer.Option(0, "--port", "-p", help="API port (default: APP_PORT from .env or 8765)."),
) -> None:
    load_root_dotenv()
    root = project_root()
    backend = root / "backend"
    if not (backend / "app" / "main.py").is_file():
        console.print(
            f"[red]Cannot find backend at {backend}. "
            f"Set WF_PROJECT_ROOT to your WeatherFlow clone.[/red]"
        )
        raise typer.Exit(1)

    bind_host = (host or os.environ.get("APP_HOST") or "127.0.0.1").strip()
    bind_port = port or int(os.environ.get("APP_PORT", "8765"))

    prefix = _uvicorn_prefix(backend)
    api_args = prefix + [
        "app.main:app",
        "--host",
        bind_host,
        "--port",
        str(bind_port),
    ]
    if reload:
        api_args.append("--reload")

    if api_only:
        state_dir = root / ".weatherflow"
        state_dir.mkdir(exist_ok=True)
        pid_path = state_dir / "dev-pids.json"
        if detach:
            log_api = open(state_dir / "dev-api.log", "a", encoding="utf-8")
            kw = _popen_kwargs(detach=True)
            api_proc = subprocess.Popen(
                api_args,
                cwd=str(backend),
                stdout=log_api,
                stderr=subprocess.STDOUT,
                **kw,
            )
            pid_path.write_text(
                json.dumps(
                    {
                        "api": api_proc.pid,
                        "api_port": bind_port,
                        "front_port": dashboard_port_from_env(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            time.sleep(0.6)
            if api_proc.poll() is not None:
                log_api.close()
                try:
                    pid_path.unlink()
                except OSError:
                    pass
                console.print(
                    f"[red]API exited immediately (code {api_proc.returncode}). "
                    f"See {state_dir / 'dev-api.log'}[/red]"
                )
                raise typer.Exit(1)
            log_api.close()
            console.print(
                f"[green]API running in background[/green] → http://{bind_host}:{bind_port}\n"
                f"[dim]Log:[/dim] {state_dir / 'dev-api.log'}\n"
                f"[dim]Stop:[/dim] [bold]wf stop[/bold] (or wf stop --ports-only)"
            )
            raise typer.Exit(0)
        console.print(
            f"[dim]API only → http://{bind_host}:{bind_port} (cwd {backend})[/dim]"
        )
        raise SystemExit(subprocess.run(api_args, cwd=str(backend)).returncode)

    frontend = root / "frontend"
    if not (frontend / "package.json").is_file():
        console.print(f"[red]No frontend at {frontend}.[/red]")
        raise typer.Exit(1)
    if not (frontend / "node_modules").is_dir():
        console.print(
            "[yellow]Frontend dependencies missing. Run:[/yellow]\n"
            f"  cd {frontend} && npm install"
        )
        raise typer.Exit(1)

    npm = shutil.which("npm")
    if not npm:
        console.print("[red]npm not found in PATH. Install Node.js to run the dashboard.[/red]")
        raise typer.Exit(1)

    dash = (os.environ.get("WF_DASHBOARD_URL") or "http://127.0.0.1:3000").strip()
    kw = _popen_kwargs(detach=detach)
    stop_hint = (
        "[dim]Background mode: logs under .weatherflow/; stop with [bold]wf stop[/bold].[/dim]\n"
        if detach
        else "[dim]Press Ctrl+C to stop both, or run [bold]wf stop[/bold] from another terminal.[/dim]\n"
    )
    console.print(
        f"[dim]Starting API + dashboard dev server…[/dim]\n"
        f"  API:  [bold]http://{bind_host}:{bind_port}[/bold]\n"
        f"  Web:  [bold]{dash}[/bold]  (after Next is ready)\n"
        f"{stop_hint}"
    )

    state_dir = root / ".weatherflow"
    state_dir.mkdir(exist_ok=True)
    pid_path = state_dir / "dev-pids.json"
    log_api_path = state_dir / "dev-api.log"
    log_front_path = state_dir / "dev-front.log"

    if detach:
        log_api = open(log_api_path, "a", encoding="utf-8")
        log_front = open(log_front_path, "a", encoding="utf-8")
        try:
            api_proc = subprocess.Popen(
                api_args,
                cwd=str(backend),
                stdout=log_api,
                stderr=subprocess.STDOUT,
                **kw,
            )
            front_proc = subprocess.Popen(
                [npm, "run", "dev"],
                cwd=str(frontend),
                stdout=log_front,
                stderr=subprocess.STDOUT,
                **kw,
            )
        finally:
            log_api.close()
            log_front.close()
    else:
        api_proc = subprocess.Popen(api_args, cwd=str(backend), **kw)
        front_proc = subprocess.Popen([npm, "run", "dev"], cwd=str(frontend), **kw)

    pid_path.write_text(
        json.dumps(
            {
                "api": api_proc.pid,
                "front": front_proc.pid,
                "api_port": bind_port,
                "front_port": dashboard_port_from_env(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if detach:
        time.sleep(0.8)
        failed: list[str] = []
        if api_proc.poll() is not None:
            failed.append(f"API (exit {api_proc.returncode})")
        if front_proc.poll() is not None:
            failed.append(f"frontend (exit {front_proc.returncode})")
        if failed:
            try:
                pid_path.unlink()
            except OSError:
                pass
            console.print(
                f"[red]Startup failed: {', '.join(failed)}. "
                f"See {log_api_path} and {log_front_path}[/red]"
            )
            _terminate_tree(api_proc)
            _terminate_tree(front_proc)
            _reap(api_proc)
            _reap(front_proc)
            raise typer.Exit(1)
        console.print(
            f"[green]Running in background.[/green]\n"
            f"[dim]Logs:[/dim] {log_api_path}\n"
            f"           {log_front_path}\n"
            f"[dim]Stop:[/dim] [bold]wf stop[/bold]"
        )
        raise typer.Exit(0)

    exit_code = 0
    try:
        while True:
            if api_proc.poll() is not None:
                console.print("[yellow]API process exited.[/yellow]")
                exit_code = api_proc.returncode or 0
                break
            if front_proc.poll() is not None:
                console.print("[yellow]Frontend process exited.[/yellow]")
                exit_code = front_proc.returncode or 0
                break
            time.sleep(0.35)
    except KeyboardInterrupt:
        console.print("[dim]Stopping…[/dim]")
        exit_code = 0
    finally:
        _terminate_tree(api_proc)
        _terminate_tree(front_proc)
        _reap(api_proc)
        _reap(front_proc)
        try:
            if pid_path.is_file():
                pid_path.unlink()
        except OSError:
            pass

    raise SystemExit(exit_code)
