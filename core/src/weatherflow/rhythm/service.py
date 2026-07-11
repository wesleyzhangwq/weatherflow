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
            events = await self.ledger.list_stream_in(
                connection, "workspace", workspace_id, limit=1000
            )
            facts: list[SignalFact] = []
            for stored in events:
                if not stored.type.startswith("rhythm.signal."):
                    continue
                parsed = TypeAdapter(RhythmSignal).validate_python(stored.payload["signal"])
                facts.append((stored.id, parsed))
            observed_now = max(datetime.now(UTC), signal.observed_at)
            snapshot = self.estimator.estimate(workspace_id, facts, now=observed_now)
            await self.snapshots.save_in(connection, snapshot)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="rhythm.snapshot_derived",
                    actor=Actor.SYSTEM,
                    stream_kind="rhythm_snapshot",
                    stream_id=snapshot.id,
                    correlation_id=workspace_id,
                    causation_id=event.id,
                    payload={
                        "workspace_id": workspace_id,
                        "supporting_event_ids": list(snapshot.supporting_event_ids),
                        "estimator_version": snapshot.estimator_version,
                    },
                ),
            )
        return self._current(snapshot, now=observed_now)

    async def current(self, workspace_id: str) -> CurrentRhythm:
        snapshot = await self.snapshots.get(workspace_id)
        now = datetime.now(UTC)
        if snapshot is None:
            snapshot = self.estimator.estimate(workspace_id, [], now=now)
        return self._current(snapshot, now=now)

    @staticmethod
    def _current(snapshot: HumanStateSnapshot, *, now: datetime) -> CurrentRhythm:
        return CurrentRhythm(
            snapshot=snapshot,
            policy=project_policy(snapshot, now=now),
            weather=project_weather(snapshot, now=now),
        )
