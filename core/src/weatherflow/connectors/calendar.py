from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from weatherflow.capabilities import ToolSpec
from weatherflow.capabilities.builtin.operations import (
    MAX_CALENDAR_EVENTS,
    CalendarEvent,
)
from weatherflow.connectors.tools import COMPOSIO_TOOLS_BY_ID
from weatherflow.runtime import (
    PublicToolError,
    ToolExecutionContext,
    ToolExecutionResult,
)

CALENDAR_TIMEZONE = ZoneInfo("Asia/Shanghai")


class CalendarComposioExecutor(Protocol):
    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...


class ComposioCalendarAdapter:
    """Typed Calendar provider backed by the reviewed Composio tool boundary.

    The adapter deliberately delegates every remote call to ``ComposioToolExecutor``.
    That executor validates the frozen per-Run connector route, active binding,
    granted connector scope, reviewed action/version, and bounded output projection.
    Provider tokens never cross this adapter.
    """

    def __init__(self, *, executor: CalendarComposioExecutor) -> None:
        self.executor = executor

    async def list_events(
        self,
        *,
        start: str,
        end: str,
        limit: int,
        context: ToolExecutionContext,
    ) -> tuple[CalendarEvent, ...]:
        bounded_limit = max(1, min(limit, MAX_CALENDAR_EVENTS))
        result = await self.executor.execute(
            _canonical_spec("composio.google_calendar.list_events"),
            {
                "timeMin": start,
                "timeMax": end,
                "maxResults": bounded_limit,
            },
            context,
        )
        data = _result_data(result)
        raw_events = data.get("items") or data.get("events") or []
        if not isinstance(raw_events, list):
            raise PublicToolError("connector_result_invalid")
        events: list[CalendarEvent] = []
        for raw in raw_events[:bounded_limit]:
            event = _calendar_event(raw)
            if event is not None:
                events.append(event)
        return tuple(events)

    async def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        idempotency_key: str,
        context: ToolExecutionContext,
    ) -> CalendarEvent:
        if (
            context.action_id is None
            or context.idempotency_key is None
            or context.idempotency_key != idempotency_key
        ):
            raise PermissionError("Calendar mutation requires an approved Action context")
        start_at = _aware_datetime(start, "start")
        end_at = _aware_datetime(end, "end")
        duration_seconds = (end_at - start_at).total_seconds()
        if duration_seconds <= 0 or duration_seconds % 60:
            raise ValueError("Calendar event duration must be a positive whole number of minutes")
        duration_minutes = int(duration_seconds // 60)
        if duration_minutes > 1440:
            raise ValueError("Calendar event duration exceeds 1440 minutes")
        localized_start = start_at.astimezone(CALENDAR_TIMEZONE)
        result = await self.executor.execute(
            _canonical_spec("composio.google_calendar.create_event"),
            {
                "summary": title,
                "start_datetime": localized_start.isoformat(),
                "timezone": str(CALENDAR_TIMEZONE),
                "event_duration_minutes": duration_minutes,
            },
            context,
        )
        data = _result_data(result)
        raw_event = data.get("event") if isinstance(data.get("event"), dict) else data
        event = _calendar_event(raw_event)
        if event is None:
            raise PublicToolError("connector_result_invalid")
        return event


def _canonical_spec(tool_id: str) -> ToolSpec:
    definition = COMPOSIO_TOOLS_BY_ID.get(tool_id)
    if definition is None:
        raise LookupError(tool_id)
    return definition.spec()


def _result_data(result: ToolExecutionResult) -> dict[str, Any]:
    data = result.output.get("data")
    if not result.output.get("ok") or not isinstance(data, dict):
        raise PublicToolError("connector_result_invalid")
    return data


def _calendar_event(raw: Any) -> CalendarEvent | None:
    if not isinstance(raw, dict):
        return None
    event_id = raw.get("id")
    title = raw.get("summary")
    start = _calendar_time(raw.get("start"))
    end = _calendar_time(raw.get("end"))
    url = raw.get("htmlLink") or raw.get("html_link")
    if not all(isinstance(value, str) and value.strip() for value in (event_id, title, start, end)):
        return None
    if not isinstance(url, str):
        url = None
    try:
        return CalendarEvent(
            event_id=event_id.strip(),
            title=title.strip(),
            start=start.strip(),
            end=end.strip(),
            url=url.strip() if url else None,
        )
    except ValidationError:
        return None


def _calendar_time(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    result = value.get("dateTime") or value.get("date_time") or value.get("date")
    return result if isinstance(result, str) else None


def _aware_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed
