from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.continuations import ProviderAssistantMessage
from weatherflow.runs import RunStatus
from weatherflow.runtime import FinalTurn, LoopStatus, ModelCompletion, ToolCallTurn

KEY = bytes(range(32))
PRIVATE_REASONING = "provider-private-reasoning-never-in-checkpoint"


class PauseAfterToolModel:
    continuation_provider = "minimax"
    continuation_model = "MiniMax-M2.7"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelCompletion(
                turn=ToolCallTurn(
                    call_id="call-recovery",
                    tool_id="developer.read_file",
                    arguments={"path": "note.txt"},
                ),
                continuation=ProviderAssistantMessage(
                    provider=self.continuation_provider,
                    model=self.continuation_model,
                    payload={
                        "role": "assistant",
                        "content": None,
                        "reasoning_details": [{"text": PRIVATE_REASONING}],
                        "tool_calls": [{"id": "call-recovery"}],
                    },
                ),
            )
        raise TimeoutError("pause after the persisted tool turn")


class ResumeWithContinuationModel:
    continuation_provider = "minimax"
    continuation_model = "MiniMax-M2.7"

    def __init__(self) -> None:
        self.observed = ()

    async def complete(self, request):
        self.observed = request.provider_continuations
        assert self.observed[0].payload["reasoning_details"][0]["text"] == PRIVATE_REASONING
        return FinalTurn(content="Recovered with exact provider history")


async def test_encrypted_continuation_survives_restart_but_not_terminal_run(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "note.txt").write_text("durable", encoding="utf-8")
    settings = Settings(data_dir=tmp_path)
    first_model = PauseAfterToolModel()
    first = await RuntimeContainer.create(
        settings,
        model=first_model,
        provider_continuation_key=KEY,
    )

    run, outcome = await first.submit_run(
        user_intent="Read note.txt and answer",
        client_request_id="provider-continuation-restart",
    )

    assert outcome is not None and outcome.status is LoopStatus.PAUSED
    checkpoint = await first.checkpoints.get(run.id)
    assert checkpoint is not None
    assert PRIVATE_REASONING not in checkpoint.model_dump_json()
    async with first.database.connect() as connection:
        table_names = [
            row["name"]
            for row in await (
                await connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "AND name != 'provider_continuations'"
                )
            ).fetchall()
        ]
        durable_domain_rows = []
        for table_name in table_names:
            durable_domain_rows.extend(
                await (await connection.execute(f'SELECT * FROM "{table_name}"')).fetchall()
            )
        assert PRIVATE_REASONING not in repr(durable_domain_rows)
        before = await (
            await connection.execute(
                "SELECT COUNT(*) FROM provider_continuations WHERE run_id = ?", (run.id,)
            )
        ).fetchone()
    assert before[0] == 1

    resumed_model = ResumeWithContinuationModel()
    rebuilt = await RuntimeContainer.create(
        settings,
        model=resumed_model,
        provider_continuation_key=KEY,
    )

    resumed = await rebuilt.resume_run(run.id)

    assert resumed.status is LoopStatus.SUCCEEDED
    assert resumed_model.observed
    stored = await rebuilt.runs.get(run.id)
    assert stored is not None and stored.status is RunStatus.SUCCEEDED
    async with rebuilt.database.connect() as connection:
        after = await (
            await connection.execute(
                "SELECT COUNT(*) FROM provider_continuations WHERE run_id = ?", (run.id,)
            )
        ).fetchone()
    assert after[0] == 0
