#!/usr/bin/env python3
"""Run the Tauri development app with the rustup toolchain on PATH."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> None:
    cargo = subprocess.run(
        ["rustup", "which", "cargo"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = os.environ.copy()
    environment["PATH"] = f"{Path(cargo).parent}:{environment.get('PATH', '')}"
    os.execvpe(
        "pnpm",
        ["pnpm", "--filter", "weatherflow-desktop", "exec", "tauri", "dev"],
        environment,
    )


if __name__ == "__main__":
    main()
