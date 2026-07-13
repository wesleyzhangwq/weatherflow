from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from weatherflow.continuations import (
    ContinuationCipher,
    ProviderContinuationRepository,
    ProviderContinuationUnavailableError,
)
from weatherflow.events import EventLedger
from weatherflow.runs import RunCoordinator, RunRepository
from weatherflow.storage import Database

KEY = bytes(range(32))
PRIVATE_REASONING = "private-reasoning-must-stay-encrypted"


async def setup(tmp_path: Path, *, now: datetime | None = None):
    database = Database(tmp_path / "weatherflow.db")
    await database.initialize()
    ledger = EventLedger(database)
    runs = RunRepository(database)
    run = await RunCoordinator(database, runs, ledger).create_run(
        client_request_id="continuation-test",
        user_intent="Read a file",
        workspace_id="workspace-1",
    )
    clock = [now or datetime(2026, 7, 13, tzinfo=UTC)]
    repository = ProviderContinuationRepository(
        database=database,
        cipher=ContinuationCipher(KEY),
        now=lambda: clock[0],
    )
    return database, run, repository, clock


async def test_continuation_is_aead_encrypted_and_bound_to_run_model_and_step(
    tmp_path: Path,
) -> None:
    database, run, repository, _ = await setup(tmp_path)
    payload = {
        "role": "assistant",
        "content": None,
        "reasoning_details": [{"text": PRIVATE_REASONING}],
        "tool_calls": [{"id": "call-1"}],
    }

    saved = await repository.save(
        run_id=run.id,
        step_index=1,
        provider="minimax",
        model="MiniMax-M2.7",
        payload=payload,
    )

    async with database.connect() as connection:
        row = await (
            await connection.execute(
                "SELECT nonce, ciphertext, payload_sha256 FROM provider_continuations "
                "WHERE run_id = ? AND step_index = 1",
                (run.id,),
            )
        ).fetchone()
    assert len(row["nonce"]) == 12
    assert PRIVATE_REASONING.encode() not in row["ciphertext"]
    assert len(row["payload_sha256"]) == 64
    assert saved.payload == payload
    assert await repository.require_for_run(
        run.id,
        provider="minimax",
        model="MiniMax-M2.7",
        required_steps=(1,),
    ) == (saved,)


async def test_tampering_and_model_mismatch_fail_closed(tmp_path: Path) -> None:
    database, run, repository, _ = await setup(tmp_path)
    await repository.save(
        run_id=run.id,
        step_index=1,
        provider="minimax",
        model="MiniMax-M2.7",
        payload={"role": "assistant", "reasoning_details": [{"text": PRIVATE_REASONING}]},
    )

    with pytest.raises(ProviderContinuationUnavailableError):
        await repository.require_for_run(
            run.id,
            provider="minimax",
            model="MiniMax-M2.5",
            required_steps=(1,),
        )

    async with database.transaction() as connection:
        row = await (
            await connection.execute(
                "SELECT ciphertext FROM provider_continuations WHERE run_id = ?",
                (run.id,),
            )
        ).fetchone()
        damaged = bytes([row["ciphertext"][0] ^ 1]) + row["ciphertext"][1:]
        await connection.execute(
            "UPDATE provider_continuations SET ciphertext = ? WHERE run_id = ?",
            (damaged, run.id),
        )

    with pytest.raises(ProviderContinuationUnavailableError):
        await repository.require_for_run(
            run.id,
            provider="minimax",
            model="MiniMax-M2.7",
            required_steps=(1,),
        )


async def test_expired_continuation_is_deleted_and_cannot_be_replayed(tmp_path: Path) -> None:
    database, run, repository, clock = await setup(tmp_path)
    await repository.save(
        run_id=run.id,
        step_index=1,
        provider="minimax",
        model="MiniMax-M2.7",
        payload={"role": "assistant", "reasoning_details": [{"text": PRIVATE_REASONING}]},
        retention=timedelta(hours=1),
    )
    clock[0] += timedelta(hours=2)

    with pytest.raises(ProviderContinuationUnavailableError):
        await repository.require_for_run(
            run.id,
            provider="minimax",
            model="MiniMax-M2.7",
            required_steps=(1,),
        )

    async with database.connect() as connection:
        count = await (
            await connection.execute(
                "SELECT COUNT(*) FROM provider_continuations WHERE run_id = ?", (run.id,)
            )
        ).fetchone()
    assert count[0] == 0
