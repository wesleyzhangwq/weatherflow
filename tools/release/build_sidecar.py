#!/usr/bin/env python3
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "core" / "src" / "weatherflow" / "__main__.py"
BUNDLED_SKILLS = (
    ROOT / "core" / "src" / "weatherflow" / "resources" / "wesley-skills"
)
TAURI_BINARY = (
    ROOT
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "weatherflow-core-aarch64-apple-darwin"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=TAURI_BINARY)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("WeatherFlow release sidecar must be built on arm64 macOS")
    build_root = ROOT / "release" / "pyinstaller"
    shutil.rmtree(build_root, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "weatherflow-core",
        "--paths",
        str(ROOT / "core" / "src"),
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "keyring",
        "--hidden-import",
        "weatherflow.api.app",
        "--add-data",
        f"{BUNDLED_SKILLS}:weatherflow/resources/wesley-skills",
        "--distpath",
        str(build_root / "dist"),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root),
        str(ENTRYPOINT),
    ]
    environment = {**os.environ, "PYTHONHASHSEED": "0"}
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    built = build_root / "dist" / "weatherflow-core"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, args.output)
    args.output.chmod(0o755)
    inspection = subprocess.run(
        ["file", str(args.output)], check=True, text=True, capture_output=True
    ).stdout
    if "Mach-O 64-bit executable arm64" not in inspection:
        raise SystemExit(f"unexpected sidecar architecture: {inspection.strip()}")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
