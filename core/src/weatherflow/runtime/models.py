from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.capabilities.models import ToolSpec


class LeafDelegationError(ValueError):
    pass


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class FinalTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["final"] = "final"
    content: str
    usage: ModelUsage = ModelUsage()


class ToolCallTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["tool_call"] = "tool_call"
    call_id: str | None = None
    tool_id: str
    arguments: dict[str, Any]
    usage: ModelUsage = ModelUsage()


class DelegationTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["delegation"] = "delegation"
    agent_id: str
    task: str
    usage: ModelUsage = ModelUsage()


ModelTurn = Annotated[
    FinalTurn | ToolCallTurn | DelegationTurn,
    Field(discriminator="kind"),
]


class AgentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    system_prompt: str
    is_leaf: bool = False
    tool_filter: frozenset[str] = frozenset()
    skill_filter: frozenset[str] = frozenset()
    max_steps: int = Field(default=20, ge=1)

    def validate_turn(self, turn: ModelTurn) -> ModelTurn:
        if self.is_leaf and isinstance(turn, DelegationTurn):
            raise LeafDelegationError(self.agent_id)
        return turn


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    agent: AgentDefinition
    messages: tuple[AgentMessage, ...]
    tools: tuple[ToolSpec, ...]


class CompactWorkerResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    summary: str
    artifact_ids: tuple[str, ...] = ()
    status: Literal["succeeded", "failed"]


class ToolExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    workspace_id: str
    action_id: str | None = None
    idempotency_key: str | None = None


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: dict[str, Any]
    artifact_ids: tuple[str, ...] = ()
