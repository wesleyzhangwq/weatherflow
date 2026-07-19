import hashlib
from datetime import date
from typing import Any, Protocol

from weatherflow.artifacts import ArtifactManifest, ArtifactStore
from weatherflow.capabilities.builtin.operations import CalendarEvent, CalendarProvider
from weatherflow.capabilities.models import IdempotencyKind, ToolEffect, ToolSpec
from weatherflow.rhythm import CurrentRhythm
from weatherflow.runtime import ToolExecutionContext, ToolExecutionResult
from weatherflow.workspaces import Workspace, WorkspaceRepository

MAX_TASKS = 50
MAX_OBJECTIVES = 20


class RhythmReader(Protocol):
    async def current(self, workspace_id: str) -> CurrentRhythm: ...


def personal_tool_specs() -> tuple[ToolSpec, ...]:
    common = {"source": "builtin.personal_operations", "source_version": "1"}
    return (
        ToolSpec(
            tool_id="personal.plan_day",
            description="Create a deterministic rhythm-aware local day-plan artifact",
            input_schema={
                "type": "object",
                "required": ["date", "tasks"],
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_TASKS,
                    },
                },
            },
            output_schema={"type": "object"},
            effect=ToolEffect.WORKSPACE_WRITE,
            required_scopes=frozenset({"workspace:write"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
        ToolSpec(
            tool_id="personal.prepare_meeting",
            description="Read a bounded Calendar window and create a source-linked prep artifact",
            input_schema={
                "type": "object",
                "required": ["start", "end", "event_id"],
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "event_id": {"type": "string"},
                    "objectives": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_OBJECTIVES,
                    },
                },
            },
            output_schema={"type": "object"},
            effect=ToolEffect.NETWORK_READ,
            required_scopes=frozenset({"workspace:write", "calendar:read"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
        ToolSpec(
            tool_id="personal.propose_schedule",
            description=(
                "Create a rhythm-aware schedule proposal artifact without mutating Calendar"
            ),
            input_schema={
                "type": "object",
                "required": ["start", "end", "tasks"],
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_TASKS,
                    },
                },
            },
            output_schema={"type": "object"},
            effect=ToolEffect.NETWORK_READ,
            required_scopes=frozenset({"workspace:write", "calendar:read"}),
            idempotency=IdempotencyKind.KEY,
            **common,
        ),
    )


class PersonalOperationsExecutor:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        artifacts: ArtifactStore,
        rhythm: RhythmReader,
        calendar: CalendarProvider | None,
    ) -> None:
        self.workspaces = workspaces
        self.artifacts = artifacts
        self.rhythm = rhythm
        self.calendar = calendar

    async def execute(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        workspace = await self.workspaces.get(context.workspace_id)
        if workspace is None:
            raise LookupError(context.workspace_id)
        current = await self.rhythm.current(workspace.id)
        if tool.tool_id == "personal.plan_day":
            return await self._plan_day(arguments, context, workspace, current)
        if tool.tool_id == "personal.prepare_meeting":
            return await self._prepare_meeting(arguments, context, workspace, current)
        if tool.tool_id == "personal.propose_schedule":
            return await self._propose_schedule(arguments, context, workspace, current)
        raise LookupError(tool.tool_id)

    async def _plan_day(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        workspace: Workspace,
        current: CurrentRhythm,
    ) -> ToolExecutionResult:
        plan_date = _date(arguments.get("date"))
        tasks = _string_list(arguments.get("tasks"), "tasks", MAX_TASKS)
        limit = 3 if current.policy.scope_pressure == "reduce" else 6
        selected, deferred = tasks[:limit], tasks[limit:]
        recovery = 30 if current.policy.interaction_budget == "minimal" else 15
        mode = (
            "Single-thread plan"
            if current.policy.work_mode.value == "single_thread"
            else "Day plan"
        )
        lines = [
            f"# {mode} — {plan_date}",
            "",
            f"Rhythm snapshot: `{current.snapshot.id}`",
            f"Recovery buffer: {recovery} minutes",
            "",
            "## Commitments",
            *(_numbered(selected) or ["1. No task supplied"]),
        ]
        if deferred:
            lines.extend(["", "## Explicitly deferred", *_bulleted(deferred)])
        content = "\n".join(lines) + "\n"
        manifest = await self._put(
            context=context,
            workspace=workspace,
            name=f"day-plan-{plan_date}.md",
            content=content,
            validation={
                "kind": "personal.day_plan",
                "rhythm_snapshot_id": current.snapshot.id,
                "rhythm_reason_refs": list(current.policy.reason_refs),
                "calendar_mutated": False,
            },
        )
        return _result(
            manifest,
            selected_tasks=selected,
            deferred_tasks=deferred,
            recovery_buffer_minutes=recovery,
        )

    async def _prepare_meeting(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        workspace: Workspace,
        current: CurrentRhythm,
    ) -> ToolExecutionResult:
        calendar = self._require_calendar()
        start = _string(arguments.get("start"), "start", 100)
        end = _string(arguments.get("end"), "end", 100)
        event_id = _string(arguments.get("event_id"), "event_id", 500)
        objectives = _string_list(arguments.get("objectives", []), "objectives", MAX_OBJECTIVES)
        events = await calendar.list_events(
            start=start,
            end=end,
            limit=50,
            context=context,
        )
        event = next((item for item in events if item.event_id == event_id), None)
        if event is None:
            raise LookupError(f"calendar event not found: {event_id}")
        content = (
            "\n".join(
                [
                    f"# Meeting preparation — {event.title}",
                    "",
                    f"Calendar source: `{event.event_id}`",
                    f"Window: {event.start} → {event.end}",
                    f"Rhythm snapshot: `{current.snapshot.id}`",
                    "",
                    "## Objectives",
                    *(_bulleted(objectives) or ["- Clarify the desired outcome"]),
                    "",
                    "## Minimum-burden preparation",
                    "- Confirm the decision needed.",
                    "- Bring only evidence relevant to that decision.",
                    "- Record owners and next actions before closing.",
                ]
            )
            + "\n"
        )
        manifest = await self._put(
            context=context,
            workspace=workspace,
            name=f"meeting-prep-{_safe_name(event.event_id)}.md",
            content=content,
            validation={
                "kind": "personal.meeting_prep",
                "calendar_event_id": event.event_id,
                "rhythm_snapshot_id": current.snapshot.id,
                "rhythm_reason_refs": list(current.policy.reason_refs),
                "calendar_mutated": False,
            },
        )
        return _result(
            manifest,
            source_event_id=event.event_id,
            rhythm_reason_refs=list(current.policy.reason_refs),
            calendar_mutated=False,
        )

    async def _propose_schedule(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        workspace: Workspace,
        current: CurrentRhythm,
    ) -> ToolExecutionResult:
        calendar = self._require_calendar()
        start = _string(arguments.get("start"), "start", 100)
        end = _string(arguments.get("end"), "end", 100)
        tasks = _string_list(arguments.get("tasks"), "tasks", MAX_TASKS)
        events = await calendar.list_events(
            start=start,
            end=end,
            limit=50,
            context=context,
        )
        limit = 2 if current.policy.scope_pressure == "reduce" else 4
        selected, deferred = tasks[:limit], tasks[limit:]
        content = (
            "\n".join(
                [
                    "# Schedule proposal — Proposal only",
                    "",
                    "This artifact does not mutate Calendar. To accept a block, request an "
                    "approved `calendar.create_event` Action.",
                    "",
                    f"Window: {start} → {end}",
                    f"Existing Calendar events: {len(events)}",
                    f"Rhythm snapshot: `{current.snapshot.id}`",
                    "",
                    "## Proposed focus blocks",
                    *(_numbered(selected) or ["1. No task supplied"]),
                    "",
                    "## Existing commitments",
                    *(_event_lines(events) or ["- None returned"]),
                    "",
                    "## Deferred",
                    *(_bulleted(deferred) or ["- None"]),
                ]
            )
            + "\n"
        )
        manifest = await self._put(
            context=context,
            workspace=workspace,
            name=f"schedule-proposal-{hashlib.sha256(f'{start}:{end}'.encode()).hexdigest()[:12]}.md",
            content=content,
            validation={
                "kind": "personal.schedule_proposal",
                "calendar_event_ids": [event.event_id for event in events],
                "rhythm_snapshot_id": current.snapshot.id,
                "rhythm_reason_refs": list(current.policy.reason_refs),
                "calendar_mutated": False,
            },
        )
        return _result(
            manifest,
            selected_tasks=selected,
            deferred_tasks=deferred,
            calendar_mutated=False,
            requires_calendar_action=bool(selected),
        )

    async def _put(
        self,
        *,
        context: ToolExecutionContext,
        workspace: Workspace,
        name: str,
        content: str,
        validation: dict[str, Any],
    ) -> ArtifactManifest:
        encoded = content.encode()
        digest = hashlib.sha256(encoded).hexdigest()
        existing = next(
            (
                item
                for item in await self.artifacts.repository.list_run(context.run_id)
                if item.name == name and item.digest == digest and item.validation == validation
            ),
            None,
        )
        return existing or await self.artifacts.put_bytes(
            run_id=context.run_id,
            workspace=workspace,
            name=name,
            media_type="text/markdown",
            data=encoded,
            validation=validation,
        )

    def _require_calendar(self) -> CalendarProvider:
        if self.calendar is None:
            raise RuntimeError("Calendar provider is unavailable")
        return self.calendar


def _result(manifest: ArtifactManifest, **values: Any) -> ToolExecutionResult:
    return ToolExecutionResult(
        output={
            "artifact_id": manifest.id,
            "digest": manifest.digest,
            **values,
        },
        artifact_ids=(manifest.id,),
    )


def _string(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{name} must be a bounded string")
    return value.strip()


def _date(value: Any) -> str:
    parsed = date.fromisoformat(_string(value, "date", 10))
    return parsed.isoformat()


def _string_list(value: Any, name: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded string array")
    return [_string(item, name, 500) for item in value]


def _safe_name(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _numbered(values: list[str]) -> list[str]:
    return [f"{index}. {value}" for index, value in enumerate(values, 1)]


def _bulleted(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values]


def _event_lines(events: tuple[CalendarEvent, ...]) -> list[str]:
    return [f"- {event.start}–{event.end}: {event.title} (`{event.event_id}`)" for event in events]
