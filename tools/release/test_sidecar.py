#!/usr/bin/env python3
import argparse
import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    token = "sidecar-smoke-token"
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="weatherflow-sidecar-") as data_dir:
        environment = {
            "HOME": data_dir,
            "PATH": "/usr/bin:/bin",
            "WF_BRIDGE_TOKEN": token,
        }
        process = subprocess.Popen(
            [
                str(binary),
                "--data-dir",
                data_dir,
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with urllib.request.urlopen(request, timeout=1) as response:
                        payload = json.load(response)
                    if payload["status"] == "ok":
                        source_request = urllib.request.Request(
                            f"http://127.0.0.1:{port}/v1/watch/source-status",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        with urllib.request.urlopen(
                            source_request,
                            timeout=60,
                        ) as response:
                            source = json.load(response)
                        required = {
                            "reachable",
                            "server_version",
                            "data_start",
                            "data_end",
                            "checked_at",
                            "last_reconciled_at",
                            "error_code",
                        }
                        if not isinstance(source, dict) or not required.issubset(
                            source
                        ):
                            raise RuntimeError(
                                "sidecar Watch source-status contract is invalid"
                            )
                        print(
                            json.dumps(
                                {
                                    **payload,
                                    "watch_source_status": "ok",
                                    "activitywatch_reachable": source["reachable"],
                                },
                                sort_keys=True,
                            )
                        )
                        return 0
                except Exception:
                    if process.poll() is not None:
                        break
                    time.sleep(0.2)
            if process.poll() is None:
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
            raise SystemExit(
                "sidecar failed health smoke\n"
                f"returncode={process.returncode}\n"
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
