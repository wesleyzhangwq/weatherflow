"""Read-only MCP resources over WeatherFlow's memory stores.

Resources expose *state* the same way tools expose *capability*: hosts that
speak MCP can pull the user's profile, recent events, and rhythm snapshot
without any private REST API. Everything here is strictly read-only and
degrades gracefully — a missing store yields an informative JSON payload,
never an exception (a resource read must not crash a host's context load).

Store locations mirror the backend's env contract (the backend forwards
``DATA_DIR`` / ``MEMORY_MARKDOWN_DIR`` to MCP subprocesses already):

* L1 event log:  ``$DATA_DIR/weatherflow.db``  (sqlite, append-only)
* L3 profile:    ``$MEMORY_MARKDOWN_DIR/profile.md``
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _data_dir() -> Path:
    return Path(os.path.expandvars(os.environ.get("DATA_DIR", str(_REPO_ROOT / "backend" / "data")))).expanduser()


def _db_path() -> Path:
    return _data_dir() / os.environ.get("DB_FILENAME", "weatherflow.db")


def _profile_path() -> Path:
    md = os.environ.get("MEMORY_MARKDOWN_DIR", "").strip()
    base = Path(md).expanduser() if md else _data_dir() / "memory"
    return base / "profile.md"


def _unavailable(reason: str, **extra) -> str:
    return json.dumps({"available": False, "reason": reason, **extra}, ensure_ascii=False)


def _query(sql: str, args: tuple = ()) -> list[dict] | None:
    """Run a read-only query against L1; None if the store doesn't exist."""
    path = _db_path()
    if not path.is_file():
        return None
    # Read-only URI mode: a resource read must never create or lock the store.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _parse_payload(row: dict) -> dict:
    try:
        row["payload"] = json.loads(row.get("payload") or "{}")
    except json.JSONDecodeError:
        pass
    return row


def register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "weatherflow://profile",
        name="User profile (L3)",
        description="Long-term user profile — human-readable markdown, written only "
                    "through the 4-gate DelayedMemoryWriter.",
        mime_type="text/markdown",
    )
    def profile() -> str:
        path = _profile_path()
        if not path.is_file():
            return _unavailable("profile.md not found", path=str(path))
        return path.read_text(encoding="utf-8")

    @mcp.resource(
        "weatherflow://events/recent",
        name="Recent events (L1 tail)",
        description="Last 50 events from the append-only L1 event log (source of truth).",
        mime_type="application/json",
    )
    def recent_events() -> str:
        rows = _query(
            "SELECT id, type, timestamp, payload FROM events ORDER BY timestamp DESC LIMIT 50"
        )
        if rows is None:
            return _unavailable("L1 event log not found", path=str(_db_path()))
        return json.dumps([_parse_payload(r) for r in rows], ensure_ascii=False)

    @mcp.resource(
        "weatherflow://rhythm/current",
        name="Current rhythm snapshot",
        description="7-day event mix plus the latest check-in — the raw signals the "
                    "rhythm agent reasons over.",
        mime_type="application/json",
    )
    def rhythm_current() -> str:
        counts = _query(
            "SELECT type, COUNT(*) AS n FROM events "
            "WHERE timestamp >= datetime('now', '-7 days') GROUP BY type ORDER BY n DESC"
        )
        if counts is None:
            return _unavailable("L1 event log not found", path=str(_db_path()))
        checkin = _query(
            "SELECT id, timestamp, payload FROM events WHERE type='checkin' "
            "ORDER BY timestamp DESC LIMIT 1"
        ) or []
        return json.dumps(
            {
                "window_days": 7,
                "event_mix": {r["type"]: r["n"] for r in counts},
                "latest_checkin": _parse_payload(checkin[0]) if checkin else None,
            },
            ensure_ascii=False,
        )

    @mcp.resource(
        "weatherflow://hypotheses/active",
        name="Active hypotheses",
        description="Most recent rhythm hypotheses (each evidence item carries a "
                    "source_event_id back-link into L1).",
        mime_type="application/json",
    )
    def hypotheses_active() -> str:
        rows = _query(
            "SELECT id, timestamp, payload FROM events WHERE type='hypothesis' "
            "ORDER BY timestamp DESC LIMIT 5"
        )
        if rows is None:
            return _unavailable("L1 event log not found", path=str(_db_path()))
        return json.dumps([_parse_payload(r) for r in rows], ensure_ascii=False)


__all__ = ["register_resources"]
