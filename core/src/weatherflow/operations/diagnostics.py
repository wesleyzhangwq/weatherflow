import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.operations.models import DiagnosticExport, LocalMetrics
from weatherflow.storage import Database
from weatherflow.workspaces import WorkspaceRepository

REDACTED = "[redacted]"
SENSITIVE_KEYS = ("authorization", "password", "secret", "token", "credential")


class DiagnosticsService:
    def __init__(
        self,
        *,
        database: Database,
        ledger: EventLedger,
        workspaces: WorkspaceRepository,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.workspaces = workspaces

    async def metrics(self, workspace_id: str) -> LocalMetrics:
        async with self.database.connect() as connection:
            run_rows = await (
                await connection.execute(
                    """
                    SELECT status, COUNT(*) AS count FROM runs
                    WHERE workspace_id = ? GROUP BY status
                    """,
                    (workspace_id,),
                )
            ).fetchall()
            action_rows = await (
                await connection.execute(
                    """
                    SELECT a.status, COUNT(*) AS count FROM actions a
                    JOIN runs r ON r.id = a.run_id
                    WHERE r.workspace_id = ? GROUP BY a.status
                    """,
                    (workspace_id,),
                )
            ).fetchall()
            event_count = await (
                await connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM events e
                    WHERE e.stream_id = ? OR e.correlation_id = ? OR EXISTS (
                        SELECT 1 FROM runs r WHERE r.workspace_id = ?
                        AND (r.id = e.stream_id OR r.id = e.correlation_id)
                    )
                    """,
                    (workspace_id, workspace_id, workspace_id),
                )
            ).fetchone()
            pending = await (
                await connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM approvals p
                    JOIN runs r ON r.id = p.run_id
                    WHERE r.workspace_id = ? AND p.status = 'pending'
                    """,
                    (workspace_id,),
                )
            ).fetchone()
        return LocalMetrics(
            run_counts={row["status"]: int(row["count"]) for row in run_rows},
            action_counts={row["status"]: int(row["count"]) for row in action_rows},
            event_count=int(event_count["count"]),
            pending_approvals=int(pending["count"]),
        )

    async def export(self, workspace_id: str) -> DiagnosticExport:
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        metrics = await self.metrics(workspace_id)
        events = await self._recent_events(workspace_id)
        payload = {
            "schema_version": "1",
            "created_at": datetime.now(UTC).isoformat(),
            "workspace_id": workspace_id,
            "upload_attempted": False,
            "metrics": metrics.model_dump(mode="json"),
            "events": events,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > 100_000:
            raise ValueError("diagnostic export exceeds size limit")
        path = Path(workspace.internal_root) / "diagnostics" / "latest" / "diagnostic.json"
        await _atomic_write(path, encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        await self.ledger.append(
            Event.new(
                type="diagnostics.exported",
                actor=Actor.USER,
                stream_kind="workspace",
                stream_id=workspace_id,
                correlation_id=workspace_id,
                payload={"sha256": digest, "size_bytes": len(encoded), "uploaded": False},
            )
        )
        return DiagnosticExport(path=path, sha256=digest, size_bytes=len(encoded))

    async def _recent_events(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT id, type, recorded_at, sensitivity, payload FROM events
                    WHERE stream_id = ? OR correlation_id = ?
                    ORDER BY recorded_at DESC, id DESC LIMIT 100
                    """,
                    (workspace_id, workspace_id),
                )
            ).fetchall()
        values = []
        for row in rows:
            payload: Any = (
                REDACTED
                if row["sensitivity"] != Sensitivity.NORMAL.value
                else _redact(json.loads(row["payload"]))
            )
            values.append(
                {
                    "id": row["id"],
                    "type": row["type"],
                    "recorded_at": row["recorded_at"],
                    "payload": payload,
                }
            )
        return values


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if any(marker in key.lower() for marker in SENSITIVE_KEYS)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and (value.lower().startswith("bearer ") or value.startswith("sk-")):
        return REDACTED
    return value


async def _atomic_write(path: Path, data: bytes) -> None:
    import asyncio

    await asyncio.to_thread(_atomic_write_sync, path, data)


def _atomic_write_sync(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".diagnostic.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
