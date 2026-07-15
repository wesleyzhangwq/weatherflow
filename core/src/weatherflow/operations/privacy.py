import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.memory import MemoryStore
from weatherflow.operations.models import ResetCategory, ResetPreview, ResetResult
from weatherflow.storage import Database
from weatherflow.workspaces import WorkspaceRepository


class PrivacyService:
    def __init__(
        self,
        *,
        database: Database,
        ledger: EventLedger,
        memory: MemoryStore,
        workspaces: WorkspaceRepository,
        external_memory_count: Callable[[str], Awaitable[int]] | None = None,
        external_memory_reset: Callable[[str], Awaitable[int]] | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.memory = memory
        self.workspaces = workspaces
        self.external_memory_count = external_memory_count
        self.external_memory_reset = external_memory_reset

    async def preview_reset(self, workspace_id: str, category: ResetCategory) -> ResetPreview:
        async with self.database.connect() as connection:
            count = await self._count_in(connection, workspace_id, category)
        if category in {ResetCategory.MEMORY, ResetCategory.WORKSPACE}:
            count += await self._external_memory_count(workspace_id)
        return ResetPreview(category=category, count=count)

    async def reset(self, workspace_id: str, category: ResetCategory) -> ResetResult:
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        external_memory_count = 0
        external_memory_deleted = 0
        if category in {ResetCategory.MEMORY, ResetCategory.WORKSPACE}:
            external_memory_count = await self._external_memory_count(workspace_id)
            if self.external_memory_reset is not None:
                external_memory_deleted = await self.external_memory_reset(workspace_id)
        artifact_paths: list[Path] = []
        async with self.database.transaction() as connection:
            count = await self._count_in(connection, workspace_id, category) + external_memory_count
            run_rows = await (
                await connection.execute(
                    "SELECT id FROM runs WHERE workspace_id = ?", (workspace_id,)
                )
            ).fetchall()
            run_ids = [row["id"] for row in run_rows]
            categories = (
                (
                    ResetCategory.BEHAVIOR,
                    ResetCategory.MEMORY,
                    ResetCategory.PROFILE,
                    ResetCategory.ARTIFACTS,
                )
                if category is ResetCategory.WORKSPACE
                else (category,)
            )
            deleted = external_memory_deleted
            for selected in categories:
                if selected is ResetCategory.BEHAVIOR:
                    cursor = await connection.execute(
                        """
                        DELETE FROM events WHERE stream_kind = 'workspace'
                        AND stream_id = ? AND type LIKE 'rhythm.signal.%'
                        """,
                        (workspace_id,),
                    )
                    deleted += cursor.rowcount
                    await connection.execute(
                        "DELETE FROM rhythm_snapshots WHERE workspace_id = ?",
                        (workspace_id,),
                    )
                elif selected is ResetCategory.MEMORY:
                    cursor = await connection.execute(
                        "DELETE FROM episodic_memories WHERE workspace_id = ?",
                        (workspace_id,),
                    )
                    deleted += cursor.rowcount
                    await connection.execute(
                        """
                        DELETE FROM memory_search_index
                        WHERE workspace_id = ? AND entry_kind = 'episode'
                        """,
                        (workspace_id,),
                    )
                elif selected is ResetCategory.PROFILE:
                    cursor = await connection.execute(
                        "DELETE FROM profile_assertions WHERE workspace_id = ?",
                        (workspace_id,),
                    )
                    deleted += cursor.rowcount
                    await connection.execute(
                        """
                        DELETE FROM memory_search_index
                        WHERE workspace_id = ? AND entry_kind = 'profile_assertion'
                        """,
                        (workspace_id,),
                    )
                elif selected is ResetCategory.ARTIFACTS:
                    rows = await (
                        await connection.execute(
                            """
                            SELECT a.relative_path FROM artifacts a
                            JOIN runs r ON r.id = a.run_id WHERE r.workspace_id = ?
                            """,
                            (workspace_id,),
                        )
                    ).fetchall()
                    artifact_paths.extend(
                        Path(workspace.artifact_root) / row["relative_path"] for row in rows
                    )
                    cursor = await connection.execute(
                        """
                        DELETE FROM artifacts WHERE run_id IN
                        (SELECT id FROM runs WHERE workspace_id = ?)
                        """,
                        (workspace_id,),
                    )
                    deleted += cursor.rowcount
            if category is ResetCategory.WORKSPACE:
                for table in (
                    "approvals",
                    "actions",
                    "capability_snapshots",
                    "checkpoints",
                    "checkpoint_quarantine",
                    "provider_continuations",
                ):
                    cursor = await connection.execute(
                        f"DELETE FROM {table} WHERE run_id IN "
                        "(SELECT id FROM runs WHERE workspace_id = ?)",
                        (workspace_id,),
                    )
                    deleted += cursor.rowcount
                if run_ids:
                    placeholders = ",".join("?" for _ in run_ids)
                    cursor = await connection.execute(
                        f"""
                        DELETE FROM events WHERE stream_id = ? OR correlation_id = ?
                        OR stream_id IN ({placeholders})
                        OR correlation_id IN ({placeholders})
                        """,
                        (workspace_id, workspace_id, *run_ids, *run_ids),
                    )
                    deleted += cursor.rowcount
                cursor = await connection.execute(
                    "DELETE FROM runs WHERE workspace_id = ?", (workspace_id,)
                )
                deleted += cursor.rowcount
                cursor = await connection.execute(
                    "DELETE FROM onboarding_preferences WHERE workspace_id = ?",
                    (workspace_id,),
                )
                deleted += cursor.rowcount
                cursor = await connection.execute(
                    "DELETE FROM model_configurations WHERE workspace_id = ?",
                    (workspace_id,),
                )
                deleted += cursor.rowcount
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="privacy.reset_completed",
                    actor=Actor.USER,
                    stream_kind="workspace",
                    stream_id=workspace_id,
                    correlation_id=workspace_id,
                    payload={"category": category.value, "deleted_count": deleted},
                ),
            )
        for path in artifact_paths:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        result_count = deleted if category is not ResetCategory.WORKSPACE else count
        return ResetResult(category=category, deleted_count=result_count)

    async def _external_memory_count(self, workspace_id: str) -> int:
        if self.external_memory_count is None:
            return 0
        return await self.external_memory_count(workspace_id)

    async def expire(self, workspace_id: str) -> ResetResult:
        now = datetime.now(UTC)
        raw_cutoff = (now - timedelta(hours=72)).isoformat()
        aggregate_cutoff = (now - timedelta(days=90)).isoformat()
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM events WHERE stream_kind = 'workspace' AND stream_id = ?
                AND ((retention_class = 'signal_raw' AND recorded_at < ?)
                  OR (retention_class = 'signal_aggregate' AND recorded_at < ?))
                """,
                (workspace_id, raw_cutoff, aggregate_cutoff),
            )
            deleted = cursor.rowcount
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="privacy.retention_expired",
                    actor=Actor.SYSTEM,
                    stream_kind="workspace",
                    stream_id=workspace_id,
                    correlation_id=workspace_id,
                    payload={"deleted_count": deleted, "policy_version": "1"},
                ),
            )
        return ResetResult(category=ResetCategory.BEHAVIOR, deleted_count=deleted)

    async def _count_in(self, connection, workspace_id: str, category: ResetCategory) -> int:
        queries = {
            ResetCategory.BEHAVIOR: (
                "SELECT COUNT(*) AS count FROM events WHERE stream_kind = 'workspace' "
                "AND stream_id = ? AND type LIKE 'rhythm.signal.%'"
            ),
            ResetCategory.MEMORY: (
                "SELECT COUNT(*) AS count FROM episodic_memories WHERE workspace_id = ?"
            ),
            ResetCategory.PROFILE: (
                "SELECT COUNT(*) AS count FROM profile_assertions WHERE workspace_id = ?"
            ),
            ResetCategory.ARTIFACTS: (
                "SELECT COUNT(*) AS count FROM artifacts WHERE run_id IN "
                "(SELECT id FROM runs WHERE workspace_id = ?)"
            ),
        }
        if category is ResetCategory.WORKSPACE:
            content_count = sum(
                await self._count_in(connection, workspace_id, selected) for selected in queries
            )
            operational = await (
                await connection.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM runs WHERE workspace_id = ?) +
                      (SELECT COUNT(*) FROM events WHERE stream_id = ? OR correlation_id = ?) +
                      (SELECT COUNT(*) FROM onboarding_preferences WHERE workspace_id = ?)
                      + (SELECT COUNT(*) FROM model_configurations WHERE workspace_id = ?)
                      AS count
                    """,
                    (
                        workspace_id,
                        workspace_id,
                        workspace_id,
                        workspace_id,
                        workspace_id,
                    ),
                )
            ).fetchone()
            return content_count + int(operational["count"])
        row = await (await connection.execute(queries[category], (workspace_id,))).fetchone()
        return int(row["count"])
