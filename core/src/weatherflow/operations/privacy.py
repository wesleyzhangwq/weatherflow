import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.memory import MemoryStore
from weatherflow.operations.models import ResetCategory, ResetPreview, ResetResult
from weatherflow.runtime.models import AgentMessage, MessageRole
from weatherflow.storage import Database
from weatherflow.workspaces import WorkspaceRepository

ActivityRunCanceller = Callable[[tuple[str, ...]], Awaitable[None]]


def _requested_activity_tools(message: AgentMessage) -> tuple[str, ...]:
    if message.role is not MessageRole.ASSISTANT:
        return ()
    try:
        payload = json.loads(message.content)
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, dict):
        return ()
    if payload.get("kind") == "tool_call":
        tool_id = payload.get("tool_id")
        return (tool_id,) if isinstance(tool_id, str) and tool_id.startswith("activity.") else ()
    if payload.get("kind") != "tool_call_batch":
        return ()
    calls = payload.get("calls")
    if not isinstance(calls, list):
        return ()
    return tuple(
        tool_id
        for call in calls
        if isinstance(call, dict)
        and isinstance((tool_id := call.get("tool_id")), str)
        and tool_id.startswith("activity.")
    )


def _is_activity_tool_message(message: AgentMessage) -> bool:
    return (
        message.role is MessageRole.TOOL
        and isinstance(message.name, str)
        and message.name.startswith("activity.")
    )


def _scrub_activity_transcript(raw_transcript: str) -> str | None:
    try:
        values = json.loads(raw_transcript)
        messages = tuple(AgentMessage.model_validate(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not any(
        _is_activity_tool_message(message) or _requested_activity_tools(message)
        for message in messages
    ):
        return None

    scrubbed: list[AgentMessage] = []
    suppress_activity_assistant = False
    for message in messages:
        if _requested_activity_tools(message) or _is_activity_tool_message(message):
            suppress_activity_assistant = True
            continue
        if message.role is MessageRole.USER:
            suppress_activity_assistant = False
            scrubbed.append(message)
            continue
        if suppress_activity_assistant and message.role is MessageRole.ASSISTANT:
            continue
        scrubbed.append(message)

    return json.dumps(
        [message.model_dump(mode="json") for message in scrubbed],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
        external_activity_count: Callable[[], Awaitable[int]] | None = None,
        external_activity_reset: Callable[[], Awaitable[int]] | None = None,
        activity_run_canceller: ActivityRunCanceller | None = None,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.memory = memory
        self.workspaces = workspaces
        self.external_memory_count = external_memory_count
        self.external_memory_reset = external_memory_reset
        self.external_activity_count = external_activity_count
        self.external_activity_reset = external_activity_reset
        self.activity_run_canceller = activity_run_canceller

    async def preview_reset(self, workspace_id: str, category: ResetCategory) -> ResetPreview:
        async with self.database.connect() as connection:
            count = await self._count_in(connection, workspace_id, category)
        if category in {ResetCategory.MEMORY, ResetCategory.WORKSPACE}:
            count += await self._external_memory_count(workspace_id)
        if category is ResetCategory.ACTIVITY:
            count += await self._external_activity_count()
        return ResetPreview(category=category, count=count)

    async def reset(self, workspace_id: str, category: ResetCategory) -> ResetResult:
        workspace = await self.workspaces.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        external_memory_count = 0
        external_memory_deleted = 0
        external_activity_count = 0
        external_activity_deleted = 0
        activity_run_content_count = 0
        if category in {ResetCategory.MEMORY, ResetCategory.WORKSPACE}:
            external_memory_count = await self._external_memory_count(workspace_id)
            if self.external_memory_reset is not None:
                external_memory_deleted = await self.external_memory_reset(workspace_id)
        if category is ResetCategory.ACTIVITY:
            external_activity_count = await self._external_activity_count()
            async with self.database.connect() as connection:
                activity_run_content_count = await self._count_in(
                    connection,
                    workspace_id,
                    category,
                )
            activity_run_ids = await self._activity_run_ids()
            if activity_run_ids and self.activity_run_canceller is not None:
                await self.activity_run_canceller(activity_run_ids)
            if self.external_activity_reset is not None:
                external_activity_deleted = await self.external_activity_reset()
        artifact_paths: list[Path] = []
        async with self.database.transaction() as connection:
            local_count = (
                activity_run_content_count
                if category is ResetCategory.ACTIVITY
                else await self._count_in(connection, workspace_id, category)
            )
            count = local_count + external_memory_count + external_activity_count
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
            deleted = external_memory_deleted + external_activity_deleted
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
                elif selected is ResetCategory.ACTIVITY:
                    deleted += await self._reset_activity_run_content_in(connection)
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
            if category is ResetCategory.ACTIVITY:
                deleted = count
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
        if category is ResetCategory.ACTIVITY:
            await self.database.secure_compact()
        result_count = deleted if category is not ResetCategory.WORKSPACE else count
        return ResetResult(category=category, deleted_count=result_count)

    async def _external_memory_count(self, workspace_id: str) -> int:
        if self.external_memory_count is None:
            return 0
        return await self.external_memory_count(workspace_id)

    async def _external_activity_count(self) -> int:
        if self.external_activity_count is None:
            return 0
        return await self.external_activity_count()

    async def _activity_run_ids(self) -> tuple[str, ...]:
        async with self.database.connect() as connection:
            return tuple(
                run_id
                for run_id, _transcript, _state in (
                    await self._activity_checkpoint_cleanups_in(connection)
                )
            )

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
        if category is ResetCategory.ACTIVITY:
            cleanups = await self._activity_checkpoint_cleanups_in(connection)
            if not cleanups:
                return 0
            run_ids = tuple(run_id for run_id, _transcript, _state in cleanups)
            placeholders = ",".join("?" for _ in run_ids)
            row = await (
                await connection.execute(
                    f"""
                    SELECT
                      (SELECT COUNT(*) FROM runs
                       WHERE id IN ({placeholders}) AND result_summary IS NOT NULL)
                      + (SELECT COUNT(*) FROM events
                         WHERE type = 'run.result_committed'
                         AND stream_id IN ({placeholders}))
                      AS count
                    """,
                    (*run_ids, *run_ids),
                )
            ).fetchone()
            return len(cleanups) + int(row["count"])
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

    @staticmethod
    async def _activity_checkpoint_cleanups_in(
        connection,
    ) -> list[tuple[str, str, str]]:
        rows = await (
            await connection.execute("SELECT run_id, transcript, state FROM checkpoints")
        ).fetchall()
        cleanups: list[tuple[str, str, str]] = []
        for row in rows:
            scrubbed = _scrub_activity_transcript(row["transcript"])
            if scrubbed is not None:
                try:
                    state = json.loads(row["state"])
                except (TypeError, ValueError):
                    state = {}
                if not isinstance(state, dict):
                    state = {}
                for key in (
                    "pending_turn",
                    "batch_next_index",
                    "tool_free_next_turn",
                    "result_committed",
                ):
                    state.pop(key, None)
                state["activity_history_reset"] = True
                cleanups.append(
                    (
                        row["run_id"],
                        scrubbed,
                        json.dumps(
                            state,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                )
        return cleanups

    async def _reset_activity_run_content_in(self, connection) -> int:
        cleanups = await self._activity_checkpoint_cleanups_in(connection)
        if not cleanups:
            return 0
        now = datetime.now(UTC).isoformat()
        deleted = 0
        for run_id, scrubbed_transcript, scrubbed_state in cleanups:
            cursor = await connection.execute(
                """
                UPDATE checkpoints
                SET transcript = ?, state = ?, pending_action_id = NULL,
                    version = version + 1, updated_at = ?
                WHERE run_id = ?
                """,
                (scrubbed_transcript, scrubbed_state, now, run_id),
            )
            deleted += cursor.rowcount

        run_ids = tuple(run_id for run_id, _transcript, _state in cleanups)
        placeholders = ",".join("?" for _ in run_ids)
        cursor = await connection.execute(
            f"""
            UPDATE runs
            SET result_summary = NULL, version = version + 1, updated_at = ?
            WHERE id IN ({placeholders}) AND result_summary IS NOT NULL
            """,
            (now, *run_ids),
        )
        deleted += cursor.rowcount
        cursor = await connection.execute(
            f"""
            DELETE FROM events
            WHERE type = 'run.result_committed'
            AND stream_id IN ({placeholders})
            """,
            run_ids,
        )
        deleted += cursor.rowcount
        return deleted
