import json
import sqlite3
from typing import Any

import aiosqlite

from weatherflow.artifacts.models import ArtifactManifest
from weatherflow.storage import Database


class DuplicateArtifactError(ValueError):
    pass


class ArtifactRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_in(self, connection: aiosqlite.Connection, artifact: ArtifactManifest) -> None:
        try:
            await connection.execute(
                """
                INSERT INTO artifacts(
                    id, run_id, name, media_type, digest, size_bytes,
                    relative_path, validation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.name,
                    artifact.media_type,
                    artifact.digest,
                    artifact.size_bytes,
                    artifact.relative_path,
                    json.dumps(
                        artifact.validation,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    artifact.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            if "UNIQUE constraint failed" in str(error):
                raise DuplicateArtifactError(artifact.id) from error
            raise

    async def get(self, artifact_id: str) -> ArtifactManifest | None:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_run(self, run_id: str) -> list[ArtifactManifest]:
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at, id",
                    (run_id,),
                )
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def count_digest(self, digest: str) -> int:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT COUNT(*) AS count FROM artifacts WHERE digest = ?", (digest,)
                )
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _from_row(row: Any) -> ArtifactManifest:
        return ArtifactManifest.model_validate(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "name": row["name"],
                "media_type": row["media_type"],
                "digest": row["digest"],
                "size_bytes": row["size_bytes"],
                "relative_path": row["relative_path"],
                "validation": json.loads(row["validation"]),
                "created_at": row["created_at"],
            }
        )
