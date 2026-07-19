from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.capabilities.models import (
    IdempotencyKind,
    ToolEffect,
    ToolSpec,
)
from weatherflow.runtime import ToolExecutionContext, ToolExecutionResult

MAX_CALENDAR_EVENTS = 50
MAX_RELEASE_BODY_CHARS = 20_000


class CalendarEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    start: str = Field(min_length=1, max_length=100)
    end: str = Field(min_length=1, max_length=100)
    url: str | None = Field(default=None, max_length=2_000)


class GitHubRelease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = Field(min_length=1, max_length=300)
    tag: str = Field(min_length=1, max_length=200)
    status: Literal["draft", "published"]
    url: str | None = Field(default=None, max_length=2_000)


class CalendarProvider(Protocol):
    async def list_events(
        self,
        *,
        start: str,
        end: str,
        limit: int,
        context: ToolExecutionContext,
    ) -> tuple[CalendarEvent, ...]: ...

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        idempotency_key: str,
        context: ToolExecutionContext,
    ) -> CalendarEvent: ...


class GitHubProvider(Protocol):
    async def inspect_release(
        self,
        *,
        repository: str,
        tag: str,
    ) -> GitHubRelease | None: ...

    async def create_release(
        self,
        *,
        repository: str,
        tag: str,
        name: str,
        body: str,
        idempotency_key: str,
    ) -> GitHubRelease: ...


def calendar_tool_specs() -> tuple[ToolSpec, ...]:
    common = {"source": "builtin.personal_operations", "source_version": "1"}
    return (
        ToolSpec(
            tool_id="calendar.list_events",
            description="List a bounded window of Calendar events",
            input_schema={
                "type": "object",
                "required": ["start", "end"],
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_CALENDAR_EVENTS,
                    },
                },
            },
            output_schema={"type": "object"},
            effect=ToolEffect.NETWORK_READ,
            required_scopes=frozenset({"calendar:read"}),
            **common,
        ),
        ToolSpec(
            tool_id="calendar.create_event",
            description="Create a Calendar event after explicit approval",
            input_schema={
                "type": "object",
                "required": ["title", "start", "end"],
            },
            output_schema={"type": "object"},
            effect=ToolEffect.EXTERNAL_WRITE,
            required_scopes=frozenset({"calendar:write"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
    )


def github_tool_specs() -> tuple[ToolSpec, ...]:
    common = {"source": "builtin.developer.github", "source_version": "1"}
    return (
        ToolSpec(
            tool_id="github.inspect_release",
            description="Inspect an existing GitHub release without mutation",
            input_schema={
                "type": "object",
                "required": ["repository", "tag"],
            },
            output_schema={"type": "object"},
            effect=ToolEffect.NETWORK_READ,
            required_scopes=frozenset({"github:read"}),
            **common,
        ),
        ToolSpec(
            tool_id="github.create_release",
            description="Create a GitHub release after explicit approval",
            input_schema={
                "type": "object",
                "required": ["repository", "tag", "name", "body"],
            },
            output_schema={"type": "object"},
            effect=ToolEffect.EXTERNAL_WRITE,
            required_scopes=frozenset({"github:write"}),
            idempotency=IdempotencyKind.KEY,
            timeout_seconds=60,
            **common,
        ),
    )


class CalendarExecutor:
    def __init__(self, provider: CalendarProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if tool.tool_id == "calendar.list_events":
            start = _string_argument(arguments, "start", max_chars=100)
            end = _string_argument(arguments, "end", max_chars=100)
            limit = _bounded_limit(arguments.get("limit", 20), MAX_CALENDAR_EVENTS)
            events = await self.provider.list_events(
                start=start,
                end=end,
                limit=limit,
                context=context,
            )
            return ToolExecutionResult(
                output={
                    "events": [event.model_dump(mode="json") for event in events[:limit]],
                    "limit": limit,
                }
            )
        if tool.tool_id == "calendar.create_event":
            idempotency_key = _external_idempotency_key(context)
            event = await self.provider.create_event(
                title=_string_argument(arguments, "title", max_chars=300),
                start=_string_argument(arguments, "start", max_chars=100),
                end=_string_argument(arguments, "end", max_chars=100),
                idempotency_key=idempotency_key,
                context=context,
            )
            return ToolExecutionResult(output={"event": event.model_dump(mode="json")})
        raise LookupError(tool.tool_id)


class GitHubExecutor:
    def __init__(self, provider: GitHubProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        repository = _string_argument(arguments, "repository", max_chars=300)
        tag = _string_argument(arguments, "tag", max_chars=200)
        if tool.tool_id == "github.inspect_release":
            release = await self.provider.inspect_release(
                repository=repository,
                tag=tag,
            )
            return ToolExecutionResult(
                output={"release": release.model_dump(mode="json") if release else None}
            )
        if tool.tool_id == "github.create_release":
            idempotency_key = _external_idempotency_key(context)
            release = await self.provider.create_release(
                repository=repository,
                tag=tag,
                name=_string_argument(arguments, "name", max_chars=300),
                body=_string_argument(
                    arguments,
                    "body",
                    max_chars=MAX_RELEASE_BODY_CHARS,
                    allow_empty=True,
                ),
                idempotency_key=idempotency_key,
            )
            return ToolExecutionResult(output={"release": release.model_dump(mode="json")})
        raise LookupError(tool.tool_id)


def _external_idempotency_key(context: ToolExecutionContext) -> str:
    if context.action_id is None or context.idempotency_key is None:
        raise PermissionError("external mutation requires an approved Action context")
    return context.idempotency_key


def _string_argument(
    arguments: dict[str, Any],
    name: str,
    *,
    max_chars: int,
    allow_empty: bool = False,
) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > max_chars:
        raise ValueError(f"{name} is empty or exceeds size limit")
    return value


def _bounded_limit(value: Any, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("limit must be an integer")
    return max(1, min(value, maximum))
