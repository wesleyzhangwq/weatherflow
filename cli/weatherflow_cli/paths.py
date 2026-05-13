"""Resolve WeatherFlow repo root (for ``wf start`` / ``wf dashboard``)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def project_root() -> Path:
    """Package lives in ``<root>/cli/weatherflow_cli/``."""
    override = (os.environ.get("WF_PROJECT_ROOT") or os.environ.get("WEATHERFLOW_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent


def dashboard_port_from_env() -> int:
    """Parse ``WF_DASHBOARD_URL`` for TCP port (default 3000)."""
    raw = (os.environ.get("WF_DASHBOARD_URL") or "http://127.0.0.1:3000").strip()
    if "://" not in raw:
        raw = "http://" + raw
    p = urlparse(raw)
    return int(p.port) if p.port is not None else 3000


def load_root_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    p = project_root() / ".env"
    if p.is_file():
        load_dotenv(p)


__all__ = ["project_root", "load_root_dotenv", "dashboard_port_from_env"]
