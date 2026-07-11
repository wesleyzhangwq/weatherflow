from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from weatherflow.capabilities.catalog import CapabilityCatalog
from weatherflow.capabilities.repository import CapabilitySnapshotRepository
from weatherflow.capabilities.resolver import CapabilityResolver
from weatherflow.capabilities.snapshots import RunCapabilitySnapshot
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runs import Run, RunNotFoundError, RunRepository
from weatherflow.storage import Database
from weatherflow.workspaces import Workspace


class CapabilityFreezeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: RunCapabilitySnapshot
    run: Run


class CapabilitySnapshotCoordinator:
    def __init__(
        self,
        *,
        database: Database,
        snapshots: CapabilitySnapshotRepository,
        runs: RunRepository,
        ledger: EventLedger,
        resolver: CapabilityResolver,
    ) -> None:
        self.database = database
        self.snapshots = snapshots
        self.runs = runs
        self.ledger = ledger
        self.resolver = resolver

    async def freeze_for_run(
        self,
        *,
        run_id: str,
        expected_run_version: int,
        catalog: CapabilityCatalog,
        catalog_revision: str,
        workspace: Workspace,
        requested_tool_ids: Iterable[str],
        allowed_tool_ids: Iterable[str] | None = None,
    ) -> CapabilityFreezeResult:
        existing = await self.snapshots.get_by_run_id(run_id)
        if existing is not None:
            return await self._result(existing)
        tools = self.resolver.resolve(
            catalog=catalog,
            workspace=workspace,
            requested_tool_ids=requested_tool_ids,
            allowed_tool_ids=allowed_tool_ids,
        )
        snapshot = RunCapabilitySnapshot.freeze(
            run_id=run_id,
            catalog_revision=catalog_revision,
            tools=tools,
        )
        async with self.database.transaction() as connection:
            existing = await self.snapshots.get_by_run_id_in(connection, run_id)
            if existing is not None:
                run = await self.runs.get_in(connection, run_id)
                if run is None:
                    raise RunNotFoundError(run_id)
                return CapabilityFreezeResult(snapshot=existing, run=run)
            await self.snapshots.create_in(connection, snapshot)
            updated_run = await self.runs.attach_capability_snapshot_in(
                connection,
                run_id,
                snapshot.id,
                expected_run_version,
            )
            prior = await self.ledger.list_stream_in(connection, "run", run_id)
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="capability.snapshot_frozen",
                    actor=Actor.SYSTEM,
                    stream_kind="capability_snapshot",
                    stream_id=snapshot.id,
                    correlation_id=run_id,
                    causation_id=prior[-1].id if prior else None,
                    payload={
                        "digest": snapshot.digest,
                        "catalog_revision": catalog_revision,
                        "tool_ids": [tool.tool_id for tool in snapshot.tools],
                        "run_version": updated_run.version,
                    },
                ),
            )
        return CapabilityFreezeResult(snapshot=snapshot, run=updated_run)

    async def _result(self, snapshot: RunCapabilitySnapshot) -> CapabilityFreezeResult:
        run = await self.runs.get(snapshot.run_id)
        if run is None:
            raise RunNotFoundError(snapshot.run_id)
        return CapabilityFreezeResult(snapshot=snapshot, run=run)
