import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import AgentMessage
from weatherflow.storage import Database


class DuplicateCheckpointError(ValueError):
    pass


class CheckpointNotFoundError(LookupError):
    pass


class CheckpointVersionConflict(RuntimeError):
    pass


class CheckpointCorruptionError(RuntimeError):
    pass


class RunCheckpointRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, checkpoint: RunCheckpoint) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO checkpoints(
                    run_id, version, step_index, transcript, state,
                    pending_action_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(checkpoint),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateCheckpointError(checkpoint.run_id) from error
            raise

    async def get(self, run_id: str) -> RunCheckpoint | None:
        async with self.database.connect() as connection:
            try:
                return await self.get_in(connection, run_id)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise CheckpointCorruptionError(run_id) from error

    async def quarantine(self, run_id: str, *, reason: str) -> str:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute("SELECT * FROM checkpoints WHERE run_id = ?", (run_id,))
            ).fetchone()
            if row is None:
                raise LookupError(run_id)
            raw = json.dumps(
                {key: row[key] for key in row.keys()},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            digest = hashlib.sha256(raw).hexdigest()
            await connection.execute(
                """
                INSERT INTO checkpoint_quarantine(
                    run_id, reason, raw_payload, payload_sha256, quarantined_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (run_id, reason, raw, digest, datetime.now(UTC).isoformat()),
            )
            await connection.execute("DELETE FROM checkpoints WHERE run_id = ?", (run_id,))
        return digest

    async def get_in(self, connection: aiosqlite.Connection, run_id: str) -> RunCheckpoint | None:
        row = await (
            await connection.execute("SELECT * FROM checkpoints WHERE run_id = ?", (run_id,))
        ).fetchone()
        return self._from_row(row) if row else None

    async def save_in(
        self,
        connection: aiosqlite.Connection,
        checkpoint: RunCheckpoint,
        *,
        expected_version: int,
    ) -> RunCheckpoint:
        current = await self.get_in(connection, checkpoint.run_id)
        if current is None:
            raise CheckpointNotFoundError(checkpoint.run_id)
        if current.version != expected_version:
            raise CheckpointVersionConflict(checkpoint.run_id)
        updated_at = datetime.now(UTC)
        cursor = await connection.execute(
            """
            UPDATE checkpoints
            SET version = version + 1, step_index = ?, transcript = ?, state = ?,
                pending_action_id = ?, updated_at = ?
            WHERE run_id = ? AND version = ?
            """,
            (
                checkpoint.step_index,
                self._transcript_json(checkpoint.transcript),
                self._json(checkpoint.state),
                checkpoint.pending_action_id,
                updated_at.isoformat(),
                checkpoint.run_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise CheckpointVersionConflict(checkpoint.run_id)
        updated = await self.get_in(connection, checkpoint.run_id)
        if updated is None:
            raise CheckpointNotFoundError(checkpoint.run_id)
        return updated

    @classmethod
    def _values(cls, checkpoint: RunCheckpoint) -> tuple[Any, ...]:
        return (
            checkpoint.run_id,
            checkpoint.version,
            checkpoint.step_index,
            cls._transcript_json(checkpoint.transcript),
            cls._json(checkpoint.state),
            checkpoint.pending_action_id,
            checkpoint.updated_at.isoformat(),
        )

    @staticmethod
    def _transcript_json(transcript: tuple[AgentMessage, ...]) -> str:
        return json.dumps(
            [message.model_dump(mode="json") for message in transcript],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _from_row(row: Any) -> RunCheckpoint:
        return RunCheckpoint.model_validate(
            {
                "run_id": row["run_id"],
                "version": row["version"],
                "step_index": row["step_index"],
                "transcript": tuple(
                    AgentMessage.model_validate(value) for value in json.loads(row["transcript"])
                ),
                "state": json.loads(row["state"]),
                "pending_action_id": row["pending_action_id"],
                "updated_at": row["updated_at"],
            }
        )
