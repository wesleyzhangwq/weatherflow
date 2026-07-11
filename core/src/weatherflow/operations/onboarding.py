from datetime import UTC, datetime

from weatherflow.events import Actor, Event, EventLedger
from weatherflow.operations.models import OnboardingState
from weatherflow.storage import Database


class OnboardingService:
    def __init__(self, *, database: Database, ledger: EventLedger) -> None:
        self.database = database
        self.ledger = ledger

    async def get(self, workspace_id: str) -> OnboardingState:
        async with self.database.connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT * FROM onboarding_preferences WHERE workspace_id = ?",
                    (workspace_id,),
                )
            ).fetchone()
        if row is None:
            return OnboardingState(workspace_id=workspace_id)
        return OnboardingState(
            workspace_id=workspace_id,
            completed=bool(row["completed"]),
            metadata_sensor_enabled=bool(row["metadata_sensor_enabled"]),
            version=row["version"],
        )

    async def complete(
        self, workspace_id: str, *, metadata_sensor_enabled: bool
    ) -> OnboardingState:
        current = await self.get(workspace_id)
        updated = OnboardingState(
            workspace_id=workspace_id,
            completed=True,
            metadata_sensor_enabled=metadata_sensor_enabled,
            version=current.version + 1,
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO onboarding_preferences(
                    workspace_id, completed, metadata_sensor_enabled, version, updated_at
                ) VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    completed = 1,
                    metadata_sensor_enabled = excluded.metadata_sensor_enabled,
                    version = onboarding_preferences.version + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    int(metadata_sensor_enabled),
                    updated.version,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="onboarding.completed",
                    actor=Actor.USER,
                    stream_kind="workspace",
                    stream_id=workspace_id,
                    correlation_id=workspace_id,
                    payload={"metadata_sensor_enabled": metadata_sensor_enabled},
                ),
            )
        return await self.get(workspace_id)
