#!/usr/bin/env python3
"""Launch only the canonical WeatherFlow app built from the current checkout."""

from __future__ import annotations

import json
import hashlib
import os
import plistlib
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release.release_macos import (  # noqa: E402
    RELEASE_LOCK as _RELEASE_LOCK,
    exclusive_release_lock,
    release_source_digest,
)

RELEASE_LOCK = _RELEASE_LOCK
CANONICAL_APP = Path("release/macos/WeatherFlow.app")
WEATHERFLOW_GUI_EXECUTABLE = re.compile(
    r"^/(?:[^/\s]+/)*(?:WeatherFlow|WeatherFlow Dev)\.app/Contents/MacOS/"
    r"(?:WeatherFlow(?: Dev)?|weatherflow-desktop)(?:\s|$)"
)
DIRECT_DEVELOPMENT_EXECUTABLES = (
    "target/debug/weatherflow-desktop",
    "target/weatherflow-dev-signed/weatherflow-desktop",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_weatherflow_gui_process(
    command: str, *, cwd: str = "", root: Path = ROOT
) -> bool:
    """Recognize WeatherFlow GUI bundles without matching unrelated binaries."""
    if WEATHERFLOW_GUI_EXECUTABLE.search(command) is not None:
        return True
    executable = command.split(maxsplit=1)[0] if command else ""
    if not any(
        executable.endswith(suffix) for suffix in DIRECT_DEVELOPMENT_EXECUTABLES
    ):
        return False
    root_value = str(root.resolve())
    cwd_value = str(Path(cwd).resolve()) if cwd else ""
    executable_is_local = executable.startswith(f"{root_value}{os.sep}")
    cwd_is_local = cwd_value == root_value or cwd_value.startswith(
        f"{root_value}{os.sep}"
    )
    return executable_is_local and cwd_is_local


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


def _weatherflow_gui_processes() -> dict[int, str]:
    output = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    matches: dict[int, str] = {}
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        command = fields[1]
        executable = command.split(maxsplit=1)[0] if command else ""
        needs_cwd = any(
            executable.endswith(suffix) for suffix in DIRECT_DEVELOPMENT_EXECUTABLES
        )
        if is_weatherflow_gui_process(
            command,
            cwd=_process_cwd(int(fields[0])) if needs_cwd else "",
            root=ROOT,
        ):
            matches[int(fields[0])] = fields[1]
    return matches


def stop_existing_weatherflow_apps() -> None:
    """Stop old release/dev GUI instances before opening the canonical bundle."""
    targets = set(_weatherflow_gui_processes())
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 3
    while targets and time.monotonic() < deadline:
        live = set(_weatherflow_gui_processes())
        targets.intersection_update(live)
        if targets:
            time.sleep(0.05)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def validate_canonical_release() -> Path:
    """Reject missing, foreign, or stale bundles before touching a running app."""
    app = (ROOT / CANONICAL_APP).resolve()
    expected_parent = (ROOT / CANONICAL_APP.parent).resolve()
    if (
        app.parent != expected_parent
        or app.name != "WeatherFlow.app"
        or not app.is_dir()
    ):
        raise SystemExit("canonical WeatherFlow release is missing")
    plist_path = app / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise SystemExit("canonical WeatherFlow release has no Info.plist")
    metadata = plistlib.loads(plist_path.read_bytes())
    if metadata.get("CFBundleIdentifier") != "ai.weatherflow.desktop":
        raise SystemExit(
            "canonical WeatherFlow release has the wrong bundle identifier"
        )
    executable_name = metadata.get("CFBundleExecutable")
    if (
        not isinstance(executable_name, str)
        or not (app / "Contents" / "MacOS" / executable_name).is_file()
    ):
        raise SystemExit("canonical WeatherFlow release has no declared executable")
    status_path = expected_parent / "release-status.json"
    try:
        status = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(
            "canonical WeatherFlow release has no valid build provenance"
        ) from error
    built_digest = status.get("source_digest")
    current_digest = release_source_digest(ROOT)
    if not isinstance(built_digest, str) or built_digest != current_digest:
        raise SystemExit(
            "canonical WeatherFlow release is stale; rebuild it from the current sources"
        )
    sidecar = app / "Contents" / "MacOS" / "weatherflow-core"
    expected_gui_hash = status.get("gui_sha256")
    expected_sidecar_hash = status.get("sidecar_sha256")
    if (
        not sidecar.is_file()
        or not isinstance(expected_gui_hash, str)
        or not isinstance(expected_sidecar_hash, str)
        or sha256(app / "Contents" / "MacOS" / executable_name) != expected_gui_hash
        or sha256(sidecar) != expected_sidecar_hash
    ):
        raise SystemExit(
            "canonical WeatherFlow bundle content does not match its provenance"
        )
    return app


def wait_for_canonical_process(app: Path) -> None:
    expected = str(app / "Contents" / "MacOS")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        processes = _weatherflow_gui_processes()
        canonical = [
            command for command in processes.values() if command.startswith(expected)
        ]
        if len(canonical) == 1 and len(processes) == 1:
            return
        time.sleep(0.1)
    stop_existing_weatherflow_apps()
    raise SystemExit(
        "canonical WeatherFlow release did not become the only active GUI process"
    )


def launch_release() -> int:
    app = validate_canonical_release()
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=True,
    )
    stop_existing_weatherflow_apps()
    app = validate_canonical_release()
    subprocess.run(["open", "-n", str(app)], check=True)
    wait_for_canonical_process(app)
    print(app)
    return 0


def main() -> int:
    with exclusive_release_lock():
        return launch_release()


if __name__ == "__main__":
    raise SystemExit(main())
