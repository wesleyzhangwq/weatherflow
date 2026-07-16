from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter

from weatherflow.events import Actor, Event, EventLedger, RetentionClass, Sensitivity
from weatherflow.rhythm.estimator import RhythmEstimator, SignalFact
from weatherflow.rhythm.models import (
    CheckInSignal,
    CorrectionSignal,
    HumanStateSnapshot,
    RhythmPolicy,
    RhythmSignal,
    TaskBehaviorSignal,
    WeatherPresentation,
)
from weatherflow.rhythm.projections import project_policy, project_weather
from weatherflow.rhythm.repository import RhythmSnapshotRepository
from weatherflow.storage import Database


class CurrentRhythm(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: HumanStateSnapshot
    policy: RhythmPolicy
    weather: WeatherPresentation


class RhythmService:
    def __init__(
        self,
        *,
        database: Database,
        ledger: EventLedger,
        snapshots: RhythmSnapshotRepository,
        estimator: RhythmEstimator,
    ) -> None:
        self.database = database
        self.ledger = ledger
        self.snapshots = snapshots
        self.estimator = estimator

    async def ingest(self, workspace_id: str, signal: RhythmSignal) -> CurrentRhythm:
        deliberate = isinstance(signal, CheckInSignal | CorrectionSignal)
        event = Event.new(
            type=f"rhythm.signal.{signal.kind}",
            actor=Actor.USER if deliberate else Actor.SYSTEM,
            stream_kind="workspace",
            stream_id=workspace_id,
            correlation_id=workspace_id,
            payload={"signal": signal.model_dump(mode="json")},
            sensitivity=Sensitivity.PRIVATE if deliberate else Sensitivity.NORMAL,
            retention_class=(
                RetentionClass.SIGNAL_RAW if deliberate else RetentionClass.SIGNAL_AGGREGATE
            ),
        )
        async with self.database.transaction() as connection:
            await self.ledger.append_in(connection, event)
            observed_now = max(datetime.now(UTC), signal.observed_at)
            snapshot = await self._derive_in(
                connection,
                workspace_id=workspace_id,
                observed_now=observed_now,
                causation_id=event.id,
                correlation_id=workspace_id,
            )
        return self._current(snapshot, now=observed_now)

    async def record_task_behavior(
        self,
        *,
        workspace_id: str,
        run_id: str,
        outcome: str,
        observed_at: datetime,
        duration_seconds: float,
        step_count: int,
    ) -> CurrentRhythm:
        signal = TaskBehaviorSignal(
            observed_at=observed_at,
            run_id=run_id,
            outcome=outcome,
            duration_seconds=duration_seconds,
            step_count=step_count,
        )
        async with self.database.transaction() as connection:
            existing = await (
                await connection.execute(
                    """
                    SELECT 1 FROM events
                    WHERE type = 'rhythm.signal.task_behavior' AND correlation_id = ?
                    LIMIT 1
                    """,
                    (run_id,),
                )
            ).fetchone()
            if existing is not None:
                snapshot = await self.snapshots.get_in(connection, workspace_id)
                if snapshot is None:
                    raise RuntimeError("task behavior exists without a rhythm snapshot")
                return self._current(snapshot, now=observed_at)
            event = Event.new(
                type="rhythm.signal.task_behavior",
                actor=Actor.SYSTEM,
                stream_kind="workspace",
                stream_id=workspace_id,
                correlation_id=run_id,
                payload={"signal": signal.model_dump(mode="json")},
                retention_class=RetentionClass.AUDIT,
            )
            await self.ledger.append_in(connection, event)
            snapshot = await self._derive_in(
                connection,
                workspace_id=workspace_id,
                observed_now=observed_at,
                causation_id=event.id,
                correlation_id=run_id,
            )
        return self._current(snapshot, now=observed_at)

    async def current(self, workspace_id: str) -> CurrentRhythm:
        snapshot = await self.snapshots.get(workspace_id)
        now = datetime.now(UTC)
        if snapshot is None:
            snapshot = self.estimator.estimate(workspace_id, [], now=now)
        return self._current(snapshot, now=now)

    async def accept_remote_snapshot(
        self,
        snapshot: HumanStateSnapshot,
    ) -> CurrentRhythm:
        async with self.database.transaction() as connection:
            await self.snapshots.save_in(connection, snapshot)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="rhythm.snapshot_remote_inference",
                    actor=Actor.SYSTEM,
                    stream_kind="rhythm_snapshot",
                    stream_id=snapshot.id,
                    correlation_id=snapshot.workspace_id,
                    payload={
                        "workspace_id": snapshot.workspace_id,
                        "window_start": snapshot.window_start.isoformat(),
                        "window_end": snapshot.window_end.isoformat(),
                        "evidence_event_ids": list(snapshot.supporting_event_ids),
                        "estimator_version": snapshot.estimator_version,
                    },
                    retention_class=RetentionClass.AUDIT,
                ),
            )
        return self._current(snapshot, now=snapshot.observed_at)

    async def delete_activity_evidence(self, event_ids: tuple[str, ...]) -> int:
        targets = set(event_ids)
        if not targets:
            return 0
        deleted = 0
        async with self.database.transaction() as connection:
            rows = await (
                await connection.execute("SELECT workspace_id, snapshot FROM rhythm_snapshots")
            ).fetchall()
            for row in rows:
                snapshot = HumanStateSnapshot.model_validate_json(row["snapshot"])
                evidence = set(snapshot.supporting_event_ids) | set(
                    snapshot.contradicting_event_ids
                )
                for estimate in snapshot.dimensions.values():
                    evidence.update(estimate.supporting_event_ids)
                    evidence.update(estimate.contradicting_event_ids)
                if targets.intersection(evidence):
                    cursor = await connection.execute(
                        "DELETE FROM rhythm_snapshots WHERE workspace_id = ?",
                        (row["workspace_id"],),
                    )
                    deleted += cursor.rowcount

            audit_rows = await (
                await connection.execute(
                    "SELECT id, payload FROM events WHERE type = ?",
                    ("rhythm.snapshot_remote_inference",),
                )
            ).fetchall()
            for row in audit_rows:
                payload = TypeAdapter(dict[str, object]).validate_json(row["payload"])
                evidence_ids = payload.get("evidence_event_ids", [])
                if isinstance(evidence_ids, list) and targets.intersection(
                    str(value) for value in evidence_ids
                ):
                    await connection.execute("DELETE FROM events WHERE id = ?", (row["id"],))
        return deleted

    @staticmethod
    def _current(snapshot: HumanStateSnapshot, *, now: datetime) -> CurrentRhythm:
        return CurrentRhythm(
            snapshot=snapshot,
            policy=project_policy(snapshot, now=now),
            weather=project_weather(snapshot, now=now),
        )

    async def _derive_in(
        self,
        connection,
        *,
        workspace_id: str,
        observed_now: datetime,
        causation_id: str,
        correlation_id: str,
    ) -> HumanStateSnapshot:
        events = await self.ledger.list_stream_in(connection, "workspace", workspace_id, limit=1000)
        facts: list[SignalFact] = []
        for stored in events:
            if not stored.type.startswith("rhythm.signal."):
                continue
            parsed = TypeAdapter(RhythmSignal).validate_python(stored.payload["signal"])
            facts.append((stored.id, parsed))
        snapshot = self.estimator.estimate(workspace_id, facts, now=observed_now)
        await self.snapshots.save_in(connection, snapshot)
        await self.ledger.append_in(
            connection,
            Event.new(
                type="rhythm.snapshot_derived",
                actor=Actor.SYSTEM,
                stream_kind="rhythm_snapshot",
                stream_id=snapshot.id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload={
                    "workspace_id": workspace_id,
                    "supporting_event_ids": list(snapshot.supporting_event_ids),
                    "estimator_version": snapshot.estimator_version,
                },
            ),
        )
        return snapshot
