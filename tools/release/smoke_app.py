#!/usr/bin/env python3
import argparse
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

SMOKE_STARTUP_TIMEOUT_SECONDS = 30


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The owned members have exited and a protected macOS helper may still
        # transiently retain the numeric group id. It is not ours to signal.
        return False
    return True


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the smoke GUI and every supervised descendant before the next probe."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (PermissionError, ProcessLookupError):
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    executables = [
        path
        for path in (app / "Contents" / "MacOS").iterdir()
        if os.access(path, os.X_OK)
    ]
    main_binary = next(
        path for path in executables if "weatherflow-core" not in path.name
    )
    with tempfile.TemporaryDirectory(prefix="weatherflow-app-smoke-") as home:
        process = subprocess.Popen(
            [str(main_binary)],
            env={**os.environ, "HOME": home},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        child_found = False
        try:
            # A freshly linked macOS bundle can take longer to admit its first
            # sidecar while the machine is still busy with release compilation.
            deadline = time.monotonic() + SMOKE_STARTUP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                children = subprocess.run(
                    ["pgrep", "-P", str(process.pid)],
                    text=True,
                    capture_output=True,
                    check=False,
                ).stdout.split()
                for child in children:
                    command = subprocess.run(
                        ["ps", "-p", child, "-o", "command="],
                        text=True,
                        capture_output=True,
                        check=False,
                    ).stdout
                    if "weatherflow-core" in command:
                        child_found = True
                        break
                if child_found:
                    print(f"app_pid={process.pid} sidecar=supervised")
                    break
                time.sleep(0.25)
        finally:
            terminate_process_group(process)
        if child_found:
            return 0
        stdout, stderr = process.communicate(timeout=2)
        raise SystemExit(
            "unsigned app smoke failed\n"
            f"stdout={stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr={stderr.decode(errors='replace')[-2000:]}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
