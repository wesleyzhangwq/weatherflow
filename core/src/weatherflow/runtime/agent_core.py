import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.runtime.models import ModelCompletion, ModelRequest
from weatherflow.runtime.protocols import ModelAdapter


class AgentCoreEventKind(StrEnum):
    MODEL_START = "model_start"
    MODEL_RETRY = "model_retry"
    MODEL_END = "model_end"
    MODEL_ERROR = "model_error"


class AgentCoreEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AgentCoreEventKind
    run_id: str
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    turn_kind: str | None = None


AgentCoreEventSink = Callable[[AgentCoreEvent], Awaitable[None]]


class AgentCore:
    """Small provider-neutral boundary for producing one validated model turn."""

    def __init__(
        self,
        *,
        max_model_attempts: int = 3,
        retry_base_delay_seconds: float = 0.05,
    ) -> None:
        if not 1 <= max_model_attempts <= 10:
            raise ValueError("max_model_attempts must be between 1 and 10")
        if not 0 <= retry_base_delay_seconds <= 5:
            raise ValueError("retry_base_delay_seconds must be between 0 and 5")
        self.max_model_attempts = max_model_attempts
        self.retry_base_delay_seconds = retry_base_delay_seconds

    async def next_turn(
        self,
        request: ModelRequest,
        model: ModelAdapter,
        *,
        emit: AgentCoreEventSink | None = None,
    ) -> ModelCompletion:
        for attempt in range(1, self.max_model_attempts + 1):
            await _emit(
                emit,
                kind=AgentCoreEventKind.MODEL_START,
                request=request,
                attempt=attempt,
                max_attempts=self.max_model_attempts,
            )
            try:
                result = await model.complete(request)
            except (TimeoutError, ConnectionError):
                if attempt == self.max_model_attempts:
                    await _emit(
                        emit,
                        kind=AgentCoreEventKind.MODEL_ERROR,
                        request=request,
                        attempt=attempt,
                        max_attempts=self.max_model_attempts,
                    )
                    raise
                await _emit(
                    emit,
                    kind=AgentCoreEventKind.MODEL_RETRY,
                    request=request,
                    attempt=attempt,
                    max_attempts=self.max_model_attempts,
                )
                await asyncio.sleep(self.retry_base_delay_seconds * (2 ** (attempt - 1)))
                continue
            completion = (
                result if isinstance(result, ModelCompletion) else ModelCompletion(turn=result)
            )
            turn = request.agent.validate_turn(completion.turn)
            await _emit(
                emit,
                kind=AgentCoreEventKind.MODEL_END,
                request=request,
                attempt=attempt,
                max_attempts=self.max_model_attempts,
                turn_kind=turn.kind,
            )
            return completion.model_copy(update={"turn": turn})
        raise RuntimeError("unreachable")


async def _emit(
    sink: AgentCoreEventSink | None,
    *,
    kind: AgentCoreEventKind,
    request: ModelRequest,
    attempt: int,
    max_attempts: int,
    turn_kind: str | None = None,
) -> None:
    if sink is None:
        return
    await sink(
        AgentCoreEvent(
            kind=kind,
            run_id=request.run_id,
            attempt=attempt,
            max_attempts=max_attempts,
            turn_kind=turn_kind,
        )
    )
