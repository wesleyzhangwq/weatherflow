from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from weatherflow.continuations.crypto import ContinuationCipher
from weatherflow.continuations.models import (
    ProviderContinuation,
    ProviderContinuationUnavailableError,
)
from weatherflow.storage import Database

SCHEMA_VERSION = 1
DEFAULT_CONTINUATION_RETENTION = timedelta(days=7)


class ProviderContinuationRepository:
    def __init__(
        self,
        *,
        database: Database,
        cipher: ContinuationCipher,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.cipher = cipher
        self._now = now or (lambda: datetime.now(UTC))

    async def save(
        self,
        *,
        run_id: str,
        step_index: int,
        provider: str,
        model: str,
        payload: dict[str, Any],
        retention: timedelta = DEFAULT_CONTINUATION_RETENTION,
    ) -> ProviderContinuation:
        async with self.database.transaction() as connection:
            return await self.save_in(
                connection,
                run_id=run_id,
                step_index=step_index,
                provider=provider,
                model=model,
                payload=payload,
                retention=retention,
            )

    async def save_in(
        self,
        connection: aiosqlite.Connection,
        *,
        run_id: str,
        step_index: int,
        provider: str,
        model: str,
        payload: dict[str, Any],
        retention: timedelta = DEFAULT_CONTINUATION_RETENTION,
    ) -> ProviderContinuation:
        if retention <= timedelta(0) or retention > DEFAULT_CONTINUATION_RETENTION:
            raise ValueError("provider continuation retention must be within seven days")
        created_at = self._now()
        continuation = ProviderContinuation(
            run_id=run_id,
            step_index=step_index,
            provider=provider,
            model=model,
            payload=payload,
            created_at=created_at,
            expires_at=created_at + retention,
        )
        metadata = _metadata(continuation)
        encrypted = self.cipher.encrypt(metadata=metadata, payload=continuation.payload)
        try:
            await connection.execute(
                """
                INSERT INTO provider_continuations(
                    run_id, step_index, provider, model, schema_version,
                    nonce, ciphertext, payload_sha256, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    continuation.run_id,
                    continuation.step_index,
                    continuation.provider,
                    continuation.model,
                    SCHEMA_VERSION,
                    encrypted.nonce,
                    encrypted.ciphertext,
                    encrypted.payload_sha256,
                    continuation.created_at.isoformat(),
                    continuation.expires_at.isoformat(),
                ),
            )
        except aiosqlite.IntegrityError as error:
            raise ProviderContinuationUnavailableError(
                "provider continuation step already exists"
            ) from error
        return continuation

    async def require_for_run(
        self,
        run_id: str,
        *,
        provider: str,
        model: str,
        required_steps: tuple[int, ...] = (),
    ) -> tuple[ProviderContinuation, ...]:
        await self.delete_expired()
        async with self.database.connect() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT * FROM provider_continuations
                    WHERE run_id = ? ORDER BY step_index
                    """,
                    (run_id,),
                )
            ).fetchall()
            if rows and any(row["provider"] != provider or row["model"] != model for row in rows):
                raise ProviderContinuationUnavailableError(
                    "provider continuation does not match the active model"
                )
            values = tuple(self._decode(row) for row in rows)
            available = {value.step_index for value in values}
            if not set(required_steps).issubset(available):
                raise ProviderContinuationUnavailableError(
                    "required provider continuation history is unavailable"
                )
            return values

    async def delete_run(self, run_id: str) -> int:
        async with self.database.transaction() as connection:
            return await self.delete_run_in(connection, run_id)

    @staticmethod
    async def delete_run_in(connection: aiosqlite.Connection, run_id: str) -> int:
        cursor = await connection.execute(
            "DELETE FROM provider_continuations WHERE run_id = ?", (run_id,)
        )
        return cursor.rowcount

    async def delete_expired(self) -> int:
        async with self.database.transaction() as connection:
            return await self.delete_expired_in(connection)

    async def delete_expired_in(self, connection: aiosqlite.Connection) -> int:
        cursor = await connection.execute(
            "DELETE FROM provider_continuations WHERE expires_at <= ?",
            (self._now().isoformat(),),
        )
        return cursor.rowcount

    def _decode(self, row: aiosqlite.Row) -> ProviderContinuation:
        continuation = ProviderContinuation(
            run_id=row["run_id"],
            step_index=row["step_index"],
            provider=row["provider"],
            model=row["model"],
            payload={"role": "assistant"},
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )
        if row["schema_version"] != SCHEMA_VERSION:
            raise ProviderContinuationUnavailableError(
                "provider continuation schema is unsupported"
            )
        payload = self.cipher.decrypt(
            metadata=_metadata(continuation),
            nonce=row["nonce"],
            ciphertext=row["ciphertext"],
            payload_sha256=row["payload_sha256"],
        )
        try:
            return ProviderContinuation.model_validate(
                {
                    **continuation.model_dump(mode="python"),
                    "payload": payload,
                }
            )
        except ValueError as error:
            raise ProviderContinuationUnavailableError(
                "provider continuation validation failed"
            ) from error


def _metadata(continuation: ProviderContinuation) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": continuation.run_id,
        "step_index": continuation.step_index,
        "provider": continuation.provider,
        "model": continuation.model,
        "created_at": continuation.created_at.isoformat(),
        "expires_at": continuation.expires_at.isoformat(),
    }
