#!/usr/bin/env python3
import argparse
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


BRIDGE_TOKEN = "b" * 64
CREDENTIAL_TOKEN = "c" * 64
CONTINUATION_KEY = "d" * 64


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def serve_credentials(
    listener: socket.socket,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        with connection:
            request = json.loads(connection.makefile("rb").readline())
            if request.get("token") != CREDENTIAL_TOKEN:
                response = {"ok": False, "code": "unauthorized"}
            elif request.get("provider") == "provider_continuations":
                response = {"ok": True, "secret": CONTINUATION_KEY}
            else:
                response = {"ok": False, "code": "not_found"}
            connection.sendall(json.dumps(response).encode() + b"\n")


def wait_for_health(process: subprocess.Popen[bytes], port: int) -> bool:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                if json.load(response).get("status") == "ok":
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix="wf-sidecar-", dir="/tmp") as root_value:
        root = Path(root_value)
        socket_path = root / "credentials.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        listener.listen()
        listener.settimeout(0.2)
        stop = threading.Event()
        broker = threading.Thread(
            target=serve_credentials,
            args=(listener, stop),
            daemon=True,
        )
        broker.start()
        port = free_port()
        process = subprocess.Popen(
            [
                str(binary),
                "--data-dir",
                str(root / "data"),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--desktop-bootstrap-stdin",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            assert process.stdin is not None
            process.stdin.write(
                json.dumps(
                    {
                        "version": 1,
                        "bridge_token": BRIDGE_TOKEN,
                        "credential_socket": str(socket_path),
                        "credential_token": CREDENTIAL_TOKEN,
                    }
                ).encode()
                + b"\n"
            )
            process.stdin.flush()
            if wait_for_health(process, port):
                print(json.dumps({"mode": "desktop_bootstrap", "status": "ok"}))
                return 0
            stdout, stderr = process.communicate(timeout=2)
            raise SystemExit(
                "desktop sidecar failed health smoke\n"
                f"returncode={process.returncode}\n"
                f"stdout={stdout.decode(errors='replace')[-2000:]}\n"
                f"stderr={stderr.decode(errors='replace')[-2000:]}"
            )
        finally:
            if process.poll() is None:
                if process.stdin is not None:
                    process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            stop.set()
            listener.close()
            broker.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
