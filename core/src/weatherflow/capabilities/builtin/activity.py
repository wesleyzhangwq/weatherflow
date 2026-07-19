from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from weatherflow.activity.context import (
    ActivityContextPack,
    activity_context_pack_output_schema,
    safe_category_projection,
)
from weatherflow.capabilities.models import ToolEffect, ToolSpec
from weatherflow.runtime import PublicToolError, ToolExecutionContext, ToolExecutionResult


class ActivitySemanticQueries(Protocol):
    async def semantic_query(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        time_anchor: datetime | None = None,
    ) -> Any: ...


def _window_schema(*, include_limit: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "start": {"type": "string", "format": "date-time"},
        "end": {"type": "string", "format": "date-time"},
    }
    if include_limit:
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": 500}
    return {
        "type": "object",
        "required": ["start", "end"],
        "properties": properties,
        "additionalProperties": False,
    }


_WINDOW_OPERATIONS = frozenset(
    {
        "query_range",
        "app_usage",
        "category_usage",
        "afk",
        "context_switches",
        "context_pack",
    }
)


def _require_historical_window(
    operation: str,
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> None:
    """Keep ActivityWatch range reads behind the frozen Run time boundary."""

    if operation not in _WINDOW_OPERATIONS or context.time_anchor is None:
        return
    try:
        start = datetime.fromisoformat(str(arguments["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(arguments["end"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        # The frozen JSON schema and semantic query parser retain responsibility
        # for ordinary format errors.
        return
    if start.tzinfo is None or end.tzinfo is None:
        raise PublicToolError("activity_window_timezone_required")
    if start >= end:
        raise PublicToolError("activity_window_order_invalid")
    if end > context.time_anchor:
        raise PublicToolError("activity_window_after_run_anchor")


def activity_tool_specs() -> tuple[ToolSpec, ...]:
    common = {
        "effect": ToolEffect.OBSERVE,
        "required_scopes": frozenset(),
        "output_schema": {"type": "object"},
        "source": "builtin.activitywatch",
        "source_version": "2",
    }
    return (
        ToolSpec(
            tool_id="activity.context_pack",
            description=(
                "Get a bounded historical ActivityWatch chronology with exact times, "
                "durations, dynamic Categories, AFK intervals, observed transitions, "
                "coverage, and sanitized untrusted evidence"
            ),
            input_schema=_window_schema(),
            **{**common, "output_schema": activity_context_pack_output_schema()},
        ),
        ToolSpec(
            tool_id="activity.current_state",
            description="Get bounded current observed ActivityWatch facts",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            **common,
        ),
        ToolSpec(
            tool_id="activity.recent",
            description="Get a bounded recent ActivityWatch timeline as untrusted observed facts",
            input_schema={
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 10_080},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "additionalProperties": False,
            },
            **common,
        ),
        ToolSpec(
            tool_id="activity.query_range",
            description=(
                "Query a bounded time range of ActivityWatch facts with optional app or "
                "Category filters. This is a historical-only source: end must be at or "
                "before the frozen run time_anchor; for past N duration use "
                "start=time_anchor-N and end=time_anchor"
            ),
            input_schema={
                **_window_schema(include_limit=True),
                "properties": {
                    **_window_schema(include_limit=True)["properties"],
                    "app": {"type": "string", "minLength": 1, "maxLength": 300},
                    "category": {"type": "string", "minLength": 1, "maxLength": 300},
                },
            },
            **common,
        ),
        ToolSpec(
            tool_id="activity.app_usage",
            description=(
                "Recalculate application usage for a bounded historical ActivityWatch time "
                "range. end must be at or before the frozen run time_anchor; for past N "
                "duration use start=time_anchor-N and end=time_anchor"
            ),
            input_schema=_window_schema(),
            **common,
        ),
        ToolSpec(
            tool_id="activity.category_usage",
            description=(
                "Recalculate dynamic ActivityWatch Category usage for a bounded historical "
                "time range ending at or before the frozen run time_anchor"
            ),
            input_schema=_window_schema(),
            **common,
        ),
        ToolSpec(
            tool_id="activity.afk",
            description=(
                "Get observed historical ActivityWatch AFK time and current AFK state; the "
                "range end must not exceed the frozen run time_anchor"
            ),
            input_schema=_window_schema(),
            **common,
        ),
        ToolSpec(
            tool_id="activity.context_switches",
            description=(
                "Get evidence-backed application, Category, and browser context switches "
                "for a bounded historical time range ending at or before the frozen run "
                "time_anchor"
            ),
            input_schema=_window_schema(),
            **common,
        ),
        ToolSpec(
            tool_id="activity.list_summaries",
            description=("List derived six-hour, daily, weekly, biweekly, or monthly summaries"),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["stage_6h", "daily_24h", "weekly", "biweekly", "monthly"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
            **common,
        ),
    )


_OPERATIONS = {
    "activity.current_state": "current_state",
    "activity.recent": "recent",
    "activity.query_range": "query_range",
    "activity.app_usage": "app_usage",
    "activity.category_usage": "category_usage",
    "activity.afk": "afk",
    "activity.context_switches": "context_switches",
    "activity.context_pack": "context_pack",
    "activity.list_summaries": "list_summaries",
}

_TRANSIENT_OPERATIONS = frozenset(
    {
        "current_state",
        "recent",
        "query_range",
        "app_usage",
        "category_usage",
        "afk",
        "context_switches",
        "context_pack",
        "list_summaries",
    }
)


class ActivityQueryExecutor:
    def __init__(self, queries: ActivitySemanticQueries) -> None:
        self.queries = queries

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        try:
            operation = _OPERATIONS[tool.tool_id]
        except KeyError as error:
            raise LookupError(tool.tool_id) from error
        if tool.source_version == "2":
            _require_historical_window(operation, arguments, context)
        elif tool.source_version != "1":
            raise PublicToolError("activity_tool_version_unreviewed")
        result = await self.queries.semantic_query(
            operation,
            arguments,
            time_anchor=context.time_anchor if tool.source_version == "2" else None,
        )
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        if not isinstance(result, dict):
            result = {"result": result}
        if operation not in _TRANSIENT_OPERATIONS:
            return ToolExecutionResult(
                output=result,
                tool_free_next_turn=True,
            )
        checkpoint_output = (
            safe_category_projection(ActivityContextPack.model_validate(result))
            if operation == "context_pack"
            else _checkpoint_projection(
                operation=operation,
                arguments=arguments,
                result=result,
            )
        )
        return ToolExecutionResult(
            output=result,
            checkpoint_output=checkpoint_output,
            transient=True,
            tool_free_next_turn=True,
        )


def _checkpoint_projection(
    *,
    operation: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    facts = result.get("untrusted_activity_data")
    items = result.get("items")
    projection: dict[str, Any] = {
        "operation": operation,
        "fact_count": (
            len(facts) if isinstance(facts, list) else len(items) if isinstance(items, list) else 0
        ),
        "truncated": bool(result.get("truncated", False)),
        "redaction_count": max(0, int(result.get("redaction_count", 0))),
    }
    if isinstance(facts, list):
        for kind in ("window", "web", "afk"):
            projection[f"{kind}_fact_count"] = sum(
                1 for fact in facts if isinstance(fact, dict) and fact.get("kind") == kind
            )
    for field in ("active_seconds", "afk_seconds"):
        value = result.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            projection[field] = float(value)
    if operation == "category_usage" and isinstance(items, list):
        projection["category_seconds"] = {
            item["name"]: float(item["seconds"])
            for item in items[:50]
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("seconds"), (int, float))
            and item["seconds"] >= 0
        }
    if operation == "context_switches":
        for field in (
            "application_switches",
            "category_switches",
            "tab_switches",
            "context_switches",
        ):
            value = result.get(field)
            if isinstance(value, int) and value >= 0:
                projection[field] = value
    if operation == "list_summaries" and isinstance(items, list):
        projection["summary_items"] = [
            {
                key: item[key]
                for key in (
                    "summary_id",
                    "revision_number",
                    "finality",
                    "window_start",
                    "window_end",
                    "active_seconds",
                    "afk_seconds",
                    "context_switch_count",
                    "category_rule_version",
                    "evidence_count",
                )
                if key in item
            }
            for item in items[:20]
            if isinstance(item, dict)
        ]
    for field in ("window_start", "window_end", "source_health"):
        value = result.get(field)
        if not isinstance(value, str):
            argument_name = {
                "window_start": "start",
                "window_end": "end",
                "source_health": "source_health",
            }[field]
            value = arguments.get(argument_name)
        if isinstance(value, str):
            projection[field] = value
    return projection
