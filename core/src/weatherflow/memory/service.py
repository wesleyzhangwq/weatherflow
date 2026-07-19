import json
import re
from datetime import UTC, datetime
from typing import Literal

import aiosqlite

from weatherflow.events import Actor, Event, EventLedger, Sensitivity
from weatherflow.memory.models import (
    EpisodicMemory,
    MemoryRecall,
    ProfileAssertion,
    ProfileAssertionStatus,
)
from weatherflow.memory.repository import (
    EpisodeRepository,
    ProfileAssertionRepository,
    ProfileVersionConflict,
)
from weatherflow.storage import Database

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)


class MemorySourceError(ValueError):
    pass


class MemoryStore:
    def __init__(self, *, database: Database, ledger: EventLedger) -> None:
        self.database = database
        self.ledger = ledger
        self.episodes = EpisodeRepository(database)
        self.assertions = ProfileAssertionRepository(database)

    async def remember_episode(
        self,
        *,
        workspace_id: str,
        summary: str,
        source_event_ids: tuple[str, ...],
        tags: tuple[str, ...] = (),
    ) -> EpisodicMemory:
        memory = EpisodicMemory.new(
            workspace_id=workspace_id,
            summary=summary,
            source_event_ids=source_event_ids,
            tags=tags,
        )
        async with self.database.transaction() as connection:
            await self._validate_sources(connection, workspace_id, source_event_ids)
            await self.episodes.create_in(connection, memory)
            await self._index_in(
                connection,
                workspace_id=workspace_id,
                kind="episode",
                entry_id=memory.id,
                text=f"{memory.summary} {' '.join(memory.tags)}",
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="memory.episode_created",
                    actor=Actor.AGENT,
                    stream_kind="episodic_memory",
                    stream_id=memory.id,
                    correlation_id=workspace_id,
                    payload={"source_event_ids": list(memory.source_event_ids)},
                ),
            )
        return memory

    async def create_assertion(
        self,
        *,
        workspace_id: str,
        claim: str,
        confidence: float,
        evidence_event_ids: tuple[str, ...],
        origin: Literal["user", "agent", "derived"],
    ) -> ProfileAssertion:
        assertion = ProfileAssertion.new(
            workspace_id=workspace_id,
            claim=claim,
            confidence=confidence,
            evidence_event_ids=evidence_event_ids,
            origin=origin,
        )
        async with self.database.transaction() as connection:
            await self._validate_sources(connection, workspace_id, evidence_event_ids)
            await self.assertions.create_in(connection, assertion)
            await self._index_in(
                connection,
                workspace_id=workspace_id,
                kind="profile_assertion",
                entry_id=assertion.id,
                text=assertion.claim,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="memory.profile_assertion_created",
                    actor=Actor.USER if origin == "user" else Actor.AGENT,
                    stream_kind="profile_assertion",
                    stream_id=assertion.id,
                    correlation_id=workspace_id,
                    payload={
                        "origin": origin,
                        "evidence_event_ids": list(evidence_event_ids),
                        "version": assertion.version,
                    },
                ),
            )
        return assertion

    async def list_active_assertions(
        self,
        workspace_id: str,
        *,
        limit: int = 8,
    ) -> tuple[ProfileAssertion, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("profile assertion limit must be between 1 and 50")
        assertions = await self.assertions.list_workspace(workspace_id)
        return tuple(
            sorted(
                (
                    assertion
                    for assertion in assertions
                    if assertion.status is ProfileAssertionStatus.ACTIVE
                ),
                key=lambda assertion: (assertion.updated_at, assertion.id),
                reverse=True,
            )[:limit]
        )

    async def update_assertion(
        self,
        assertion_id: str,
        *,
        expected_version: int,
        claim: str | None = None,
        confidence: float | None = None,
        status: ProfileAssertionStatus | None = None,
        evidence_event_ids: tuple[str, ...] | None = None,
    ) -> ProfileAssertion:
        async with self.database.transaction() as connection:
            current = await self.assertions.get_in(connection, assertion_id)
            if current is None:
                raise LookupError(assertion_id)
            if current.version != expected_version:
                raise ProfileVersionConflict(assertion_id)
            evidence = evidence_event_ids or current.evidence_event_ids
            if evidence_event_ids is not None:
                await self._validate_sources(connection, current.workspace_id, evidence)
            now = datetime.now(UTC)
            updated = current.model_copy(
                update={
                    "claim": claim if claim is not None else current.claim,
                    "confidence": (confidence if confidence is not None else current.confidence),
                    "status": status if status is not None else current.status,
                    "evidence_event_ids": evidence,
                    "version": current.version + 1,
                    "last_confirmed_at": now,
                    "updated_at": now,
                }
            )
            updated = ProfileAssertion.model_validate(updated.model_dump(mode="python"))
            await self.assertions.update_in(connection, updated, expected_version=expected_version)
            if updated.status is ProfileAssertionStatus.ACTIVE:
                await self._index_in(
                    connection,
                    workspace_id=updated.workspace_id,
                    kind="profile_assertion",
                    entry_id=updated.id,
                    text=updated.claim,
                )
            else:
                await connection.execute(
                    """
                    DELETE FROM memory_search_index
                    WHERE entry_kind = 'profile_assertion' AND entry_id = ?
                    """,
                    (updated.id,),
                )
            changed = [
                name
                for name, value in {
                    "claim": claim,
                    "confidence": confidence,
                    "status": status,
                    "evidence_event_ids": evidence_event_ids,
                }.items()
                if value is not None
            ]
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="memory.profile_assertion_updated",
                    actor=Actor.USER,
                    stream_kind="profile_assertion",
                    stream_id=updated.id,
                    correlation_id=updated.workspace_id,
                    payload={
                        "changed_fields": changed,
                        "status": updated.status.value,
                        "version": updated.version,
                    },
                ),
            )
        return updated

    async def rebuild_index(self, workspace_id: str) -> int:
        async with self.database.transaction() as connection:
            await connection.execute(
                "DELETE FROM memory_search_index WHERE workspace_id = ?", (workspace_id,)
            )
            count = 0
            for memory in await self.episodes.list_workspace_in(connection, workspace_id):
                await self._index_in(
                    connection,
                    workspace_id=workspace_id,
                    kind="episode",
                    entry_id=memory.id,
                    text=f"{memory.summary} {' '.join(memory.tags)}",
                )
                count += 1
            for assertion in await self.assertions.list_workspace_in(connection, workspace_id):
                if assertion.status is not ProfileAssertionStatus.ACTIVE:
                    continue
                await self._index_in(
                    connection,
                    workspace_id=workspace_id,
                    kind="profile_assertion",
                    entry_id=assertion.id,
                    text=assertion.claim,
                )
                count += 1
        return count

    async def recall(
        self,
        workspace_id: str,
        query: str,
        *,
        limit: int = 5,
        max_chars: int = 4_000,
    ) -> tuple[MemoryRecall, ...]:
        if limit < 1 or limit > 20 or max_chars < 1 or max_chars > 20_000:
            raise ValueError("recall bounds exceeded")
        query_terms = _terms(query)
        if not query_terms:
            return ()
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT entry_kind, entry_id, terms FROM memory_search_index
                    WHERE workspace_id = ? ORDER BY entry_kind, entry_id
                    """,
                    (workspace_id,),
                )
            ).fetchall()
            candidates: list[MemoryRecall] = []
            for row in rows:
                score = len(query_terms.intersection(json.loads(row["terms"])))
                if score == 0:
                    continue
                recalled = await self._resolve_in(
                    connection, row["entry_kind"], row["entry_id"], score
                )
                if recalled is not None:
                    candidates.append(recalled)
        selected: list[MemoryRecall] = []
        used = 0
        ranked = sorted(
            candidates,
            key=lambda value: (-value.score, value.kind, value.entry_id),
        )
        for item in ranked:
            if len(selected) >= limit or used + len(item.text) > max_chars:
                continue
            selected.append(item)
            used += len(item.text)
        return tuple(selected)

    async def _resolve_in(
        self,
        connection: aiosqlite.Connection,
        kind: str,
        entry_id: str,
        score: int,
    ) -> MemoryRecall | None:
        if kind == "episode":
            memory = await self.episodes.get_in(connection, entry_id)
            if memory is None:
                return None
            return MemoryRecall(
                kind="episode",
                entry_id=memory.id,
                text=memory.summary,
                source_event_ids=memory.source_event_ids,
                score=score,
            )
        assertion = await self.assertions.get_in(connection, entry_id)
        if assertion is None or assertion.status is not ProfileAssertionStatus.ACTIVE:
            return None
        return MemoryRecall(
            kind="profile_assertion",
            entry_id=assertion.id,
            text=assertion.claim,
            source_event_ids=assertion.evidence_event_ids,
            score=score,
        )

    async def _validate_sources(
        self,
        connection: aiosqlite.Connection,
        workspace_id: str,
        source_event_ids: tuple[str, ...],
    ) -> None:
        placeholders = ",".join("?" for _ in source_event_ids)
        rows = await (
            await connection.execute(
                f"""
                SELECT e.id, e.sensitivity FROM events e
                WHERE e.id IN ({placeholders}) AND (
                    (e.stream_kind = 'workspace' AND e.stream_id = ?)
                    OR e.correlation_id = ?
                    OR EXISTS (
                        SELECT 1 FROM runs r
                        WHERE r.workspace_id = ?
                          AND (r.id = e.stream_id OR r.id = e.correlation_id)
                    )
                )
                """,
                (*source_event_ids, workspace_id, workspace_id, workspace_id),
            )
        ).fetchall()
        found = {row["id"]: row["sensitivity"] for row in rows}
        if set(found) != set(source_event_ids) or any(
            value == Sensitivity.SECRET_REF.value for value in found.values()
        ):
            raise MemorySourceError("memory sources must be real, local, and non-secret")

    async def _index_in(
        self,
        connection: aiosqlite.Connection,
        *,
        workspace_id: str,
        kind: str,
        entry_id: str,
        text: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO memory_search_index(
                workspace_id, entry_kind, entry_id, terms, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entry_kind, entry_id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                terms = excluded.terms,
                updated_at = excluded.updated_at
            """,
            (
                workspace_id,
                kind,
                entry_id,
                json.dumps(sorted(_terms(text)), separators=(",", ":")),
                datetime.now(UTC).isoformat(),
            ),
        )


def _terms(value: str) -> set[str]:
    terms: set[str] = set()
    for raw in TOKEN_PATTERN.findall(value):
        token = raw.lower()
        terms.add(token)
        if token.isascii() and len(token) > 4:
            for suffix in ("ing", "ed", "s"):
                if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                    terms.add(token[: -len(suffix)])
    return terms
