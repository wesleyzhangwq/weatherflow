from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiosqlite

from weatherflow.activity.models import (
    ActivityHeartbeat,
    ActivityInterval,
    ActivityPreferences,
    ActivitySource,
    require_aware,
)
from weatherflow.storage import Database


class ActivityHeartbeatOutOfOrderError(ValueError):
    pass


class ActivityPreferencesVersionConflict(RuntimeError):
    pass


class ActivityRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_preferences(self) -> ActivityPreferences:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_preferences WHERE singleton_id = 1"
                )
            ).fetchone()
        return (
            ActivityPreferences.model_validate_json(row["config"]) if row else ActivityPreferences()
        )

    async def save_preferences(
        self,
        preferences: ActivityPreferences,
        *,
        expected_version: int,
    ) -> ActivityPreferences:
        async with self.database.transaction() as connection:
            row = await (
                await connection.execute(
                    "SELECT config FROM activity_preferences WHERE singleton_id = 1"
                )
            ).fetchone()
            current = (
                ActivityPreferences.model_validate_json(row["config"])
                if row
                else ActivityPreferences()
            )
            if current.version != expected_version:
                raise ActivityPreferencesVersionConflict(expected_version)
            updated = preferences.model_copy(update={"version": expected_version + 1})
            now = datetime.now(UTC).isoformat()
            await connection.execute(
                """
                INSERT INTO activity_preferences(singleton_id, config, version, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    config = excluded.config,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (updated.model_dump_json(), updated.version, now),
            )
            return updated

    async def record_heartbeat(self, heartbeat: ActivityHeartbeat) -> ActivityInterval:
        async with self.database.transaction() as connection:
            duplicate = await self._get_by_receipt(connection, heartbeat)
            if duplicate is not None:
                return duplicate

            current = await self._latest_for_source(connection, heartbeat.source_instance)
            if current is not None and heartbeat.observed_at < current.ended_at:
                raise ActivityHeartbeatOutOfOrderError(heartbeat.source_event_id)

            interval: ActivityInterval
            gap = (
                (heartbeat.observed_at - current.ended_at).total_seconds()
                if current is not None
                else None
            )
            within_pulse = gap is not None and gap <= heartbeat.pulsetime_seconds
            if (
                current is not None
                and current.state_hash == heartbeat.state_hash()
                and within_pulse
            ):
                interval = current.model_copy(
                    update={
                        "ended_at": heartbeat.observed_at,
                        "observed_at": heartbeat.observed_at,
                        "duration_seconds": (
                            heartbeat.observed_at - current.started_at
                        ).total_seconds(),
                        "updated_at": heartbeat.observed_at,
                    }
                )
                await self._update_interval(connection, interval)
            else:
                if (
                    current is not None
                    and within_pulse
                    and heartbeat.observed_at > current.ended_at
                ):
                    current = current.model_copy(
                        update={
                            "ended_at": heartbeat.observed_at,
                            "duration_seconds": (
                                heartbeat.observed_at - current.started_at
                            ).total_seconds(),
                            "updated_at": heartbeat.observed_at,
                        }
                    )
                    await self._update_interval(connection, current)
                interval = ActivityInterval.from_heartbeat(heartbeat)
                await self._insert_interval(connection, interval)

            await connection.execute(
                """
                INSERT INTO activity_heartbeat_receipts(
                    source_instance, source_event_id, activity_event_id, observed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    heartbeat.source_instance,
                    heartbeat.source_event_id,
                    interval.id,
                    heartbeat.observed_at.isoformat(),
                ),
            )
            return interval

    async def list_events(
        self,
        *,
        start: datetime,
        end: datetime,
        source: ActivitySource | None = None,
        app_name: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        limit: int = 5_000,
        offset: int = 0,
    ) -> list[ActivityInterval]:
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        query = "SELECT * FROM activity_events WHERE started_at < ? AND ended_at >= ?"
        parameters: list[object] = [window_end.isoformat(), window_start.isoformat()]
        if source is not None:
            query += " AND source = ?"
            parameters.append(source.value)
        if app_name is not None:
            query += " AND app_name = ?"
            parameters.append(app_name)
        if domain is not None:
            query += " AND domain = ?"
            parameters.append(domain)
        if category is not None:
            query += " AND category = ?"
            parameters.append(category)
        query += " ORDER BY started_at, id LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        async with self.database.connect() as connection:
            rows = await (await connection.execute(query, parameters)).fetchall()
        return [self._from_row(row) for row in rows]

    async def list_events_for_inference(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[ActivityInterval]:
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT * FROM activity_events
                    WHERE started_at < ? AND ended_at >= ?
                    ORDER BY started_at, id
                    """,
                    (window_end.isoformat(), window_start.isoformat()),
                )
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def delete_range(self, *, start: datetime, end: datetime) -> int:
        window_start = require_aware(start)
        window_end = require_aware(end)
        if window_end <= window_start:
            raise ValueError("end must be after start")
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM activity_events
                WHERE started_at < ? AND ended_at >= ?
                """,
                (window_end.isoformat(), window_start.isoformat()),
            )
            return cursor.rowcount

    async def delete_before(self, cutoff: datetime) -> int:
        before = require_aware(cutoff)
        async with self.database.transaction() as connection:
            cursor = await connection.execute(
                "DELETE FROM activity_events WHERE ended_at < ?",
                (before.isoformat(),),
            )
            return cursor.rowcount

    async def event_ids_before(self, cutoff: datetime) -> tuple[str, ...]:
        before = require_aware(cutoff)
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT id FROM activity_events WHERE ended_at < ? ORDER BY id",
                    (before.isoformat(),),
                )
            ).fetchall()
        return tuple(row["id"] for row in rows)

    async def _get_by_receipt(
        self,
        connection: aiosqlite.Connection,
        heartbeat: ActivityHeartbeat,
    ) -> ActivityInterval | None:
        row = await (
            await connection.execute(
                """
                SELECT event.* FROM activity_heartbeat_receipts AS receipt
                JOIN activity_events AS event ON event.id = receipt.activity_event_id
                WHERE receipt.source_instance = ? AND receipt.source_event_id = ?
                """,
                (heartbeat.source_instance, heartbeat.source_event_id),
            )
        ).fetchone()
        return self._from_row(row) if row else None

    async def _latest_for_source(
        self,
        connection: aiosqlite.Connection,
        source_instance: str,
    ) -> ActivityInterval | None:
        row = await (
            await connection.execute(
                """
                SELECT * FROM activity_events
                WHERE source_instance = ?
                ORDER BY ended_at DESC, id DESC LIMIT 1
                """,
                (source_instance,),
            )
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    async def _insert_interval(
        connection: aiosqlite.Connection,
        interval: ActivityInterval,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO activity_events(
                id, source, device_id, source_instance, source_event_id,
                started_at, ended_at, observed_at, duration_seconds,
                app_name, bundle_id, window_title,
                browser_name, browser_window_id, browser_tab_id,
                url, domain, tab_title,
                audible, incognito, focused, idle_state, category,
                state_hash, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            ActivityRepository._values(interval),
        )

    @staticmethod
    async def _update_interval(
        connection: aiosqlite.Connection,
        interval: ActivityInterval,
    ) -> None:
        await connection.execute(
            """
            UPDATE activity_events
            SET ended_at = ?, observed_at = ?, duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                interval.ended_at.isoformat(),
                interval.observed_at.isoformat(),
                interval.duration_seconds,
                interval.updated_at.isoformat(),
                interval.id,
            ),
        )

    @staticmethod
    def _values(interval: ActivityInterval) -> tuple[object, ...]:
        return (
            interval.id,
            interval.source.value,
            interval.device_id,
            interval.source_instance,
            interval.source_event_id,
            interval.started_at.isoformat(),
            interval.ended_at.isoformat(),
            interval.observed_at.isoformat(),
            interval.duration_seconds,
            interval.app_name,
            interval.bundle_id,
            interval.window_title,
            interval.browser_name,
            interval.browser_window_id,
            interval.browser_tab_id,
            interval.url,
            interval.domain,
            interval.tab_title,
            interval.audible,
            interval.incognito,
            interval.focused,
            interval.idle_state.value,
            interval.category,
            interval.state_hash,
            interval.created_at.isoformat(),
            interval.updated_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: Any) -> ActivityInterval:
        return ActivityInterval(
            id=row["id"],
            source=row["source"],
            device_id=row["device_id"],
            source_instance=row["source_instance"],
            source_event_id=row["source_event_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            observed_at=row["observed_at"],
            duration_seconds=row["duration_seconds"],
            app_name=row["app_name"],
            bundle_id=row["bundle_id"],
            window_title=row["window_title"],
            browser_name=row["browser_name"],
            browser_window_id=row["browser_window_id"],
            browser_tab_id=row["browser_tab_id"],
            url=row["url"],
            domain=row["domain"],
            tab_title=row["tab_title"],
            audible=None if row["audible"] is None else bool(row["audible"]),
            incognito=None if row["incognito"] is None else bool(row["incognito"]),
            focused=None if row["focused"] is None else bool(row["focused"]),
            idle_state=row["idle_state"],
            category=row["category"],
            state_hash=row["state_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
