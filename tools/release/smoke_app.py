#!/usr/bin/env python3
import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path


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
        )
        try:
            deadline = time.monotonic() + 15
            child_found = False
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
                    return 0
                time.sleep(0.25)
            stdout, stderr = process.communicate(timeout=2)
            raise SystemExit(
                "unsigned app smoke failed\n"
                f"stdout={stdout.decode(errors='replace')[-2000:]}\n"
                f"stderr={stderr.decode(errors='replace')[-2000:]}"
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
