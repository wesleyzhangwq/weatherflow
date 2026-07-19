import json

from weatherflow.continuations import (
    ProviderContinuationRepository,
    ProviderContinuationUnavailableError,
)
from weatherflow.events import Actor, Event, EventLedger
from weatherflow.runtime.checkpoints import RunCheckpoint
from weatherflow.runtime.models import (
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    MessageRole,
    ModelCompletion,
    ModelTurn,
    ToolCallTurn,
)
from weatherflow.runtime.outcomes import BoundedObservation
from weatherflow.runtime.protocols import ModelAdapter
from weatherflow.runtime.repository import RunCheckpointRepository
from weatherflow.storage import Database


class TurnCommitter:
    """Durable commit barrier for model turns and their ordered observations."""

    def __init__(
        self,
        *,
        database: Database,
        checkpoints: RunCheckpointRepository,
        ledger: EventLedger,
        continuations: ProviderContinuationRepository | None = None,
    ) -> None:
        self.database = database
        self.checkpoints = checkpoints
        self.ledger = ledger
        self.continuations = continuations

    async def record_turn(
        self,
        checkpoint: RunCheckpoint,
        completion: ModelCompletion,
        active_model: ModelAdapter,
    ) -> RunCheckpoint:
        turn = completion.turn
        state = dict(checkpoint.state)
        state.pop("tool_free_next_turn", None)
        state["pending_turn"] = turn.model_dump(mode="json")
        prior_usage = state.get("runtime_usage", {})
        input_tokens = int(prior_usage.get("input_tokens", 0)) + turn.usage.input_tokens
        output_tokens = int(prior_usage.get("output_tokens", 0)) + turn.usage.output_tokens
        prior_cost = prior_usage.get("cost_usd")
        prior_cost_status = prior_usage.get("cost_status")
        turn_cost_status = "known" if turn.usage.cost_usd is not None else "unknown"
        cost_status = "unknown" if "unknown" in {prior_cost_status, turn_cost_status} else "known"
        cost = (
            (float(prior_cost) if prior_cost is not None else 0.0) + turn.usage.cost_usd
            if turn.usage.cost_usd is not None
            else prior_cost
        )
        if input_tokens or output_tokens or cost is not None:
            state["runtime_usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
                "cost_status": cost_status,
            }
            pricing_version = getattr(active_model, "pricing_catalog_version", None)
            if pricing_version is not None and cost_status == "known":
                state["runtime_usage"]["pricing_catalog_version"] = pricing_version
        desired = checkpoint.model_copy(
            update={
                "step_index": checkpoint.step_index + 1,
                "transcript": (*checkpoint.transcript, turn_message(turn)),
                "state": state,
            }
        )
        async with self.database.transaction() as connection:
            if completion.continuation is not None:
                if self.continuations is None:
                    raise ProviderContinuationUnavailableError(
                        "provider continuation store is unavailable"
                    )
                if isinstance(turn, FinalTurn):
                    raise ProviderContinuationUnavailableError(
                        "terminal model turn cannot carry a provider continuation"
                    )
                expected_provider = getattr(active_model, "continuation_provider", None)
                expected_model = getattr(active_model, "continuation_model", None)
                if (
                    completion.continuation.provider != expected_provider
                    or completion.continuation.model != expected_model
                ):
                    raise ProviderContinuationUnavailableError(
                        "provider continuation does not match the active model"
                    )
                await self.continuations.save_in(
                    connection,
                    run_id=checkpoint.run_id,
                    step_index=checkpoint.step_index + 1,
                    provider=completion.continuation.provider,
                    model=completion.continuation.model,
                    payload=completion.continuation.payload,
                )
            saved = await self.checkpoints.save_in(
                connection,
                desired,
                expected_version=checkpoint.version,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="runtime.turn_recorded",
                    actor=Actor.AGENT,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={
                        "kind": turn.kind,
                        "step_index": saved.step_index,
                        "usage": turn.usage.model_dump(mode="json"),
                    },
                ),
            )
        return saved

    async def record_observation(
        self,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn | DelegationTurn,
        output: dict[str, object],
        *,
        clear_pending: bool = True,
        batch_next_index: int = 1,
        tool_free_next_turn: bool = False,
    ) -> RunCheckpoint:
        observation = BoundedObservation.from_output(output)
        state = dict(checkpoint.state)
        if clear_pending:
            state.pop("pending_turn", None)
            state.pop("batch_next_index", None)
        else:
            state["batch_next_index"] = batch_next_index
        if tool_free_next_turn:
            state["tool_free_next_turn"] = True
        desired = checkpoint.model_copy(
            update={
                "transcript": (
                    *checkpoint.transcript,
                    AgentMessage(
                        role=MessageRole.TOOL,
                        name=turn.tool_id if isinstance(turn, ToolCallTurn) else turn.agent_id,
                        tool_call_id=turn.call_id if isinstance(turn, ToolCallTurn) else None,
                        content=json.dumps(
                            observation.output,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                ),
                "state": state,
                "pending_action_id": None,
            }
        )
        async with self.database.transaction() as connection:
            saved = await self.checkpoints.save_in(
                connection,
                desired,
                expected_version=checkpoint.version,
            )
            event_type = (
                "tool.executed" if isinstance(turn, ToolCallTurn) else "worker.result_observed"
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type=event_type,
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={
                        "target": turn.tool_id if isinstance(turn, ToolCallTurn) else turn.agent_id,
                        "truncated": observation.truncated,
                    },
                ),
            )
        return saved

    async def record_transient_observation(
        self,
        checkpoint: RunCheckpoint,
        turn: ToolCallTurn,
        checkpoint_output: dict[str, object],
        *,
        observation_key: str,
    ) -> RunCheckpoint:
        """Persist only a replay receipt for one non-durable observation.

        The full observation is handed to the next model request in memory by
        ``SharedTurnLoop``. Keeping the pending read-only tool turn means a
        restart safely re-runs the query instead of recovering raw source data
        from a checkpoint.
        """

        receipt = BoundedObservation.from_output(
            {
                **checkpoint_output,
                "transient_observation": True,
                "raw_activity_omitted": True,
                "observation_key": observation_key,
            }
        )
        state = dict(checkpoint.state)
        state.pop("batch_next_index", None)
        transcript = tuple(
            message
            for message in checkpoint.transcript
            if not _is_transient_receipt(message, observation_key=observation_key)
        )
        desired = checkpoint.model_copy(
            update={
                "transcript": (
                    *transcript,
                    AgentMessage(
                        role=MessageRole.TOOL,
                        name=turn.tool_id,
                        tool_call_id=turn.call_id,
                        content=json.dumps(
                            receipt.output,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                ),
                "state": state,
                "pending_action_id": None,
            }
        )
        async with self.database.transaction() as connection:
            saved = await self.checkpoints.save_in(
                connection,
                desired,
                expected_version=checkpoint.version,
            )
            await self.ledger.append_in(
                connection,
                Event.new(
                    type="tool.executed",
                    actor=Actor.SYSTEM,
                    stream_kind="run",
                    stream_id=checkpoint.run_id,
                    correlation_id=checkpoint.run_id,
                    payload={
                        "target": turn.tool_id,
                        "truncated": receipt.truncated,
                        "transient": True,
                    },
                ),
            )
        return saved


def turn_message(turn: ModelTurn) -> AgentMessage:
    if isinstance(turn, FinalTurn):
        content = turn.content
    else:
        content = json.dumps(
            turn.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return AgentMessage(role=MessageRole.ASSISTANT, content=content)


def _is_transient_receipt(message: AgentMessage, *, observation_key: str) -> bool:
    if message.role is not MessageRole.TOOL:
        return False
    try:
        payload = json.loads(message.content)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("transient_observation") is True
        and payload.get("observation_key") == observation_key
    )
