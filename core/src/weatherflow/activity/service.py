from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from weatherflow.activity.activitywatch import ActivityWatchReadClient
from weatherflow.activity.inference import (
    ActivityAnalysisRouteMismatchError,
    ActivityModelOutputRejectedError,
    ActivitySummaryAnalyzer,
)
from weatherflow.activity.models import (
    ACTIVITY_SUMMARY_PROMPT_VERSION,
    ActivitySourceHealth,
    ActivitySourceState,
    ActivitySummaryRevision,
    ActivitySummarySettings,
    ActivitySummaryTask,
    SummaryFinality,
    SummaryTaskStatus,
    SummaryTaskType,
    require_aware,
)
from weatherflow.activity.repository import ActivityRepository
from weatherflow.activity.sanitizer import ActivitySanitizer
from weatherflow.activity.semantic import (
    ActivityCategoryRulesChanged,
    ActivityQueryLimitExceeded,
    ActivitySemanticQueryService,
)
from weatherflow.activity.windows import FINAL_GRACE, PROVISIONAL_GRACE, ActivityWindowPlanner
from weatherflow.extensions import CredentialUnavailableError
from weatherflow.models.anthropic import (
    AnthropicAuthenticationError,
    AnthropicResponseError,
    AnthropicRetryableError,
)
from weatherflow.models.errors import ModelResponseFailureStage
from weatherflow.models.minimax import (
    MiniMaxAuthenticationError,
    MiniMaxResponseError,
    MiniMaxRetryableError,
)
from weatherflow.models.openai import (
    OpenAIAuthenticationError,
    OpenAIResponseError,
    OpenAIRetryableError,
)

_MODEL_RETRYABLE_ERRORS = (
    OpenAIRetryableError,
    AnthropicRetryableError,
    MiniMaxRetryableError,
)
_MODEL_AUTHENTICATION_ERRORS = (
    OpenAIAuthenticationError,
    AnthropicAuthenticationError,
    MiniMaxAuthenticationError,
)
_MODEL_RESPONSE_ERRORS = (
    OpenAIResponseError,
    AnthropicResponseError,
    MiniMaxResponseError,
)


class ActivitySummaryService:
    def __init__(
        self,
        *,
        repository: ActivityRepository,
        semantic: ActivitySemanticQueryService,
        analyzer: ActivitySummaryAnalyzer | None = None,
        planner: ActivityWindowPlanner | None = None,
    ) -> None:
        self.repository = repository
        self.semantic = semantic
        self.analyzer = analyzer or ActivitySummaryAnalyzer()
        self.planner = planner or ActivityWindowPlanner()

    async def execute_task(
        self,
        task_id: str,
        *,
        now: datetime,
        lease_owner: str = "activity-summary-scheduler",
    ) -> ActivitySummaryTask:
        observed = require_aware(now)
        source_state = await self.repository.source_state()
        if source_state is None or source_state.health is not ActivitySourceHealth.AVAILABLE:
            task = await self.repository.get_task(task_id)
            if task is None:
                raise LookupError(task_id)
            return task
        category_id = source_state.category_rule_version
        if category_id is None:
            raise RuntimeError("ActivityWatch Category version is unavailable")
        category_rules = await self.repository.category_rule_version(category_id)
        if category_rules is None:
            raise RuntimeError("ActivityWatch Category rules were not persisted")
        claimed_pair = await self.repository.claim_task(
            task_id,
            lease_owner=lease_owner,
            now=observed,
            category_rule_version=category_id,
        )
        if claimed_pair is None:
            task = await self.repository.get_task(task_id)
            if task is None:
                raise LookupError(task_id)
            return task
        task, attempt = claimed_pair
        try:
            desired_finality = self.planner.finality(task, now=observed)
            if desired_finality is None:
                raise ValueError("summary task is not beyond the provisional grace")
            previous = await self.repository.latest_revision(task.id)
            evidence = await self.semantic.collect_window(
                start=task.window_start,
                end=task.window_end,
                server_id=source_state.server_id,
                category_rules=category_rules,
            )
            lower_summaries = await self._lower_summaries(task.id)
            analysis = await self.analyzer.analyze(
                task=task,
                evidence=evidence,
                lower_summaries=lower_summaries,
            )
            finality = self._revision_finality(
                task=task,
                desired=desired_finality,
                previous=previous,
                source_watermark=evidence.statistics.source_watermark,
                category_rule_version=category_id,
            )
            generation_reason = task.regeneration_reason or (
                "finalization" if finality is SummaryFinality.FINAL else "scheduled"
            )
            durable_statistics = evidence.statistics.model_copy(
                update={
                    "application_seconds": {},
                    "domain_seconds": {},
                }
            )
            revision = ActivitySummaryRevision(
                id="pending",
                task_id=task.id,
                revision_number=max(1, task.current_revision + 1),
                generation_id=attempt.id,
                generation_reason=generation_reason,
                finality=finality,
                statistics=durable_statistics,
                summary_text=analysis.summary_text,
                evidence_refs=evidence.evidence_refs,
                connector_evidence_refs=analysis.connector_evidence_refs,
                connector_coverage=analysis.connector_coverage,
                category_rule_version=category_id,
                category_rules_json=category_rules.canonical_json,
                provider=analysis.provider,
                model=analysis.model,
                requested_provider=analysis.requested_provider,
                requested_model=analysis.requested_model,
                configuration_version=analysis.configuration_version,
                summary_settings_version=analysis.summary_settings_version,
                prompt_version=analysis.prompt_version,
                statistics_version=evidence.statistics.statistics_version,
                request_digest=analysis.request_digest,
                redaction_count=analysis.redaction_count,
                usage=analysis.usage,
                fallback_reason=analysis.fallback_reason,
                source_watermark=evidence.statistics.source_watermark,
                completed_at=observed,
            )
            next_retry_at = self._next_retry(
                task=task,
                finality=finality,
                now=observed,
            )
            completed, _stored_revision = await self.repository.complete_attempt(
                task_id=task.id,
                attempt_id=attempt.id,
                revision=revision,
                now=observed,
                next_retry_at=next_retry_at,
            )
        except Exception as error:
            error_code, retryable, failure_stage = self._error_policy(error)
            return await self.repository.fail_attempt(
                task_id=task.id,
                attempt_id=attempt.id,
                error_code=error_code,
                now=observed,
                retryable=retryable,
                failure_stage=failure_stage,
            )
        return completed

    async def request_regeneration(
        self,
        task_id: str,
        *,
        now: datetime,
        reason: str,
    ) -> ActivitySummaryTask:
        return await self.repository.request_regeneration(
            task_id,
            now=now,
            reason=reason,
        )

    async def _lower_summaries(
        self,
        task_id: str,
    ) -> tuple[ActivitySummaryRevision, ...]:
        dependencies = await self.repository.dependencies_for(task_id)
        revisions: list[ActivitySummaryRevision] = []
        for dependency in dependencies:
            revision = await self.repository.latest_revision(dependency.child_task_id)
            if revision is not None:
                revisions.append(revision)
        revisions.sort(
            key=lambda revision: (
                revision.statistics.window_start,
                revision.task_id,
                revision.revision_number,
            )
        )
        return tuple(revisions[-24:])

    @staticmethod
    def _revision_finality(
        *,
        task: ActivitySummaryTask,
        desired: SummaryFinality,
        previous: ActivitySummaryRevision | None,
        source_watermark: str,
        category_rule_version: str,
    ) -> SummaryFinality:
        if desired is SummaryFinality.PROVISIONAL:
            return SummaryFinality.PROVISIONAL
        if previous is None:
            return SummaryFinality.PROVISIONAL
        stable = (
            previous.source_watermark == source_watermark
            and previous.category_rule_version == category_rule_version
        )
        if stable:
            return SummaryFinality.FINAL
        return SummaryFinality.PROVISIONAL

    @staticmethod
    def _next_retry(
        *,
        task: ActivitySummaryTask,
        finality: SummaryFinality,
        now: datetime,
    ) -> datetime | None:
        if finality is SummaryFinality.FINAL:
            return None
        final_boundary = task.window_end + FINAL_GRACE
        if now < final_boundary:
            return final_boundary
        return now + PROVISIONAL_GRACE

    @staticmethod
    def _error_policy(
        error: Exception,
    ) -> tuple[str, bool, ModelResponseFailureStage | None]:
        import httpx

        from weatherflow.activity.models import (
            ActivityWatchProtocolError,
            ActivityWatchUnavailable,
        )

        if isinstance(error, ActivityWatchUnavailable):
            return "activitywatch_unavailable", True, None
        if isinstance(error, ActivityCategoryRulesChanged):
            return "activity_category_rules_changed", True, None
        if isinstance(
            error,
            (*_MODEL_RETRYABLE_ERRORS, httpx.TimeoutException, httpx.NetworkError),
        ):
            return "activity_model_temporarily_unavailable", True, None
        if isinstance(error, ActivityAnalysisRouteMismatchError):
            return "activity_model_route_version_mismatch", True, None
        if isinstance(error, CredentialUnavailableError) or _has_cause(
            error,
            CredentialUnavailableError,
        ):
            return "activity_model_credential_unavailable", True, None
        if isinstance(error, _MODEL_AUTHENTICATION_ERRORS):
            return "activity_model_provider_authentication_failed", True, None
        if isinstance(error, ActivityModelOutputRejectedError):
            return (
                "activity_model_output_rejected",
                False,
                ModelResponseFailureStage.MODEL_OUTPUT,
            )
        if isinstance(error, _MODEL_RESPONSE_ERRORS):
            return "activity_model_invalid_response", False, error.stage
        if isinstance(error, ActivityQueryLimitExceeded):
            return "activity_query_safety_bound", False, None
        if isinstance(error, ActivityWatchProtocolError):
            return "activitywatch_protocol_error", False, None
        if isinstance(error, (ValueError, LookupError)):
            return "activity_summary_validation_failed", False, None
        return "activity_summary_failed", False, None


def _has_cause(error: BaseException, expected: type[BaseException]) -> bool:
    observed: BaseException | None = error.__cause__
    seen: set[int] = set()
    while observed is not None and id(observed) not in seen:
        if isinstance(observed, expected):
            return True
        seen.add(id(observed))
        observed = observed.__cause__
    return False


class ActivityService:
    """Application façade for Watch API, scheduler, and model-visible reads."""

    def __init__(
        self,
        *,
        client: ActivityWatchReadClient,
        repository: ActivityRepository,
        semantic: ActivitySemanticQueryService | None = None,
        summaries: ActivitySummaryService | None = None,
        recovery: Any = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.semantic = semantic or ActivitySemanticQueryService(
            client=client,
            repository=repository,
        )
        self.summaries = summaries or ActivitySummaryService(
            repository=repository,
            semantic=self.semantic,
        )
        self.sanitizer = ActivitySanitizer()
        self.recovery = recovery

    def attach_recovery(self, recovery: Any) -> None:
        self.recovery = recovery

    async def close(self) -> None:
        await self.client.close()

    async def source_status(self) -> ActivitySourceState:
        state = await self.repository.source_state()
        if state is not None:
            return state
        return ActivitySourceState(
            health=ActivitySourceHealth.DEGRADED,
            checked_at=datetime.now(UTC),
            error_code="activitywatch_not_checked",
        )

    async def summary_settings(self) -> ActivitySummarySettings:
        settings = await self.repository.summary_settings()
        if settings is None:
            raise RuntimeError("activity summary settings are unavailable")
        return settings

    async def update_summary_settings(
        self,
        *,
        model_workspace_id: str,
        provider: str,
        model: str,
        model_configuration_version: int,
        expected_version: int,
        now: datetime | None = None,
    ) -> ActivitySummarySettings:
        current = await self.summary_settings()
        candidate = ActivitySummarySettings(
            model_workspace_id=model_workspace_id,
            provider=provider,
            model=model,
            model_configuration_version=model_configuration_version,
            prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
            version=current.version,
            updated_at=now or datetime.now(UTC),
        )
        return await self.repository.save_summary_settings(
            candidate,
            expected_version=expected_version,
            now=now or datetime.now(UTC),
        )

    async def current_state(self, *, now: datetime | None = None):
        return await self.semantic.current_state(now=now or datetime.now(UTC))

    async def recent_activity(
        self,
        *,
        now: datetime | None = None,
        minutes: int = 60,
        limit: int = 200,
    ):
        return await self.semantic.recent_activity(
            now=now or datetime.now(UTC),
            minutes=minutes,
            limit=limit,
        )

    async def query_range(self, **arguments):
        return await self.semantic.query_range(**arguments)

    async def timeline(self, **arguments):
        return await self.semantic.timeline(**arguments)

    async def dashboard_window(self, **arguments):
        return await self.semantic.dashboard_window(**arguments)

    async def statistics(self, **arguments):
        return await self.semantic.statistics(**arguments)

    async def application_usage(self, **arguments):
        return await self.semantic.application_usage(**arguments)

    async def category_usage(self, **arguments):
        return await self.semantic.category_usage(**arguments)

    async def afk_status(self, **arguments):
        return await self.semantic.afk_status(**arguments)

    async def context_switches(self, **arguments):
        return await self.semantic.context_switches(**arguments)

    async def context_pack(self, **arguments):
        return await self.semantic.context_pack(**arguments)

    async def summary_history(
        self,
        *,
        kind: SummaryTaskType | str | None = None,
        task_type: SummaryTaskType | None = None,
        limit: int = 100,
    ):
        resolved = task_type or (SummaryTaskType(kind) if isinstance(kind, str) else kind)
        return await self.semantic.summary_history(
            task_type=resolved,
            limit=limit,
        )

    async def list_summaries(
        self,
        *,
        kind: SummaryTaskType | str | None = None,
        task_type: SummaryTaskType | None = None,
        limit: int = 100,
    ):
        return await self.summary_history(
            kind=kind,
            task_type=task_type,
            limit=limit,
        )

    async def get_summary(self, summary_id: str):
        return await self.semantic.get_summary(summary_id)

    async def list_tasks(
        self,
        *,
        status=None,
        statuses=None,
        limit: int = 500,
    ):
        resolved = statuses
        if resolved is None and status is not None:
            if isinstance(status, (tuple, list)):
                resolved = tuple(
                    item if hasattr(item, "value") else SummaryTaskStatus(item) for item in status
                )
            else:
                resolved = (status if hasattr(status, "value") else SummaryTaskStatus(status),)
        return await self.semantic.list_tasks(statuses=resolved, limit=limit)

    async def trends(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        granularity: str | None = None,
        task_type: SummaryTaskType | None = None,
        limit: int = 90,
    ):
        return await self.semantic.trends(
            start=start,
            end=end,
            granularity=granularity,
            task_type=task_type,
            limit=limit,
        )

    async def request_regeneration(
        self,
        task_id: str,
        *,
        now: datetime | None = None,
        reason: str,
    ) -> ActivitySummaryTask:
        return await self.summaries.request_regeneration(
            task_id,
            now=now or datetime.now(UTC),
            reason=reason,
        )

    async def reconcile(self, *, now: datetime | None = None):
        if self.recovery is None:
            raise RuntimeError("activity recovery coordinator is not attached")
        return await self.recovery.reconcile(now=now or datetime.now(UTC))

    async def prepare(self, *, now: datetime | None = None):
        if self.recovery is None:
            raise RuntimeError("activity recovery coordinator is not attached")
        return await self.recovery.prepare(now=now or datetime.now(UTC))

    async def tick(self, *, now: datetime | None = None):
        return await self.reconcile(now=now)

    async def history_count(self) -> int:
        return await self.repository.history_count()

    async def reset_history(self, *, now: datetime | None = None) -> int:
        return await self.repository.reset_history(now=now or datetime.now(UTC))

    async def clear_history_cutoff(
        self,
        *,
        now: datetime | None = None,
    ) -> ActivitySourceState:
        return await self.repository.clear_history_cutoff(now=now or datetime.now(UTC))

    async def semantic_query(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        time_anchor: datetime | None = None,
    ) -> Any:
        if operation == "current_state":
            current = await self.current_state(now=time_anchor)
            current_facts = tuple(
                fact for fact in (current.observed, current.web_context) if fact is not None
            )
            return self._model_fact_envelope(
                current_facts,
                metadata={
                    "observed_at": current.observed_at.isoformat(),
                    "source_health": current.source_health.value,
                    "afk_state": current.afk_state.value,
                },
            )
        if operation == "recent":
            result = await self.recent_activity(
                now=time_anchor,
                minutes=int(arguments.get("minutes", 60)),
                limit=int(arguments.get("limit", 200)),
            )
            return self._model_fact_envelope(
                result.facts,
                metadata={
                    "window_start": result.window_start.isoformat(),
                    "window_end": result.window_end.isoformat(),
                },
                truncated=result.truncated,
            )
        if operation == "query_range":
            result = await self.query_range(
                start=_parse_datetime(arguments["start"]),
                end=_parse_datetime(arguments["end"]),
                limit=int(arguments.get("limit", 500)),
                app_name=arguments.get("app"),
                category=arguments.get("category"),
            )
            return self._model_fact_envelope(
                result.facts,
                metadata={
                    "window_start": result.window_start.isoformat(),
                    "window_end": result.window_end.isoformat(),
                },
                truncated=result.truncated,
            )
        if operation == "app_usage":
            items = await self.application_usage(**_window_arguments(arguments))
            return self._model_named_items(items)
        if operation == "category_usage":
            items = await self.category_usage(**_window_arguments(arguments))
            return self._model_named_items(items)
        if operation == "afk":
            window = await self.afk_status(**_window_arguments(arguments))
            current = await self.current_state()
            return {
                "data_classification": "derived_activity_statistics",
                "instructions_allowed": False,
                **window,
                "current": current.afk_state.value,
            }
        if operation == "context_switches":
            return {
                "data_classification": "derived_activity_statistics",
                "instructions_allowed": False,
                **await self.context_switches(**_window_arguments(arguments)),
            }
        if operation == "context_pack":
            pack = await self.context_pack(**_window_arguments(arguments))
            return pack.model_dump(mode="json")
        if operation == "list_summaries":
            task_type = (
                SummaryTaskType(arguments["kind"]) if arguments.get("kind") is not None else None
            )
            summaries = await self.list_summaries(
                task_type=task_type,
                limit=int(arguments.get("limit", 100)),
            )
            return self._model_summary_envelope(summaries)
        raise LookupError(operation)

    def _model_fact_envelope(
        self,
        facts,
        *,
        metadata: dict[str, Any] | None = None,
        truncated: bool = False,
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "data_classification": "untrusted_activity_records",
            "instructions_allowed": False,
            "untrusted_activity_data": [],
            "truncated": truncated,
            "redaction_count": 0,
            **(metadata or {}),
        }
        for fact in tuple(facts)[:120]:
            sanitized = self.sanitizer.sanitize(fact)
            candidate = {
                **envelope,
                "untrusted_activity_data": [
                    *envelope["untrusted_activity_data"],
                    sanitized.event,
                ],
                "redaction_count": envelope["redaction_count"] + sanitized.redaction_count,
            }
            if (
                len(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                > 128 * 1024
            ):
                envelope["truncated"] = True
                break
            envelope = candidate
        if len(tuple(facts)) > len(envelope["untrusted_activity_data"]):
            envelope["truncated"] = True
        return envelope

    def _model_named_items(self, items) -> dict[str, Any]:
        projected: list[dict[str, Any]] = []
        redaction_count = 0
        truncated = False
        for item in tuple(items)[:120]:
            name, count = self.sanitizer.sanitize_text(item.name)
            candidate = [*projected, {"name": name, "seconds": item.seconds}]
            envelope = {
                "data_classification": "untrusted_activity_labels",
                "instructions_allowed": False,
                "items": candidate,
                "redaction_count": redaction_count + count,
                "truncated": False,
            }
            if (
                len(json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                > 128 * 1024
            ):
                truncated = True
                break
            projected = candidate
            redaction_count += count
        if len(tuple(items)) > len(projected):
            truncated = True
        return {
            "data_classification": "untrusted_activity_labels",
            "instructions_allowed": False,
            "items": projected,
            "redaction_count": redaction_count,
            "truncated": truncated,
        }

    def _model_summary_envelope(
        self,
        summaries: list[ActivitySummaryRevision],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        redaction_count = 0
        truncated = False
        for summary in summaries[:100]:
            narrative, count = self.sanitizer.sanitize_text(summary.summary_text[:2_000])
            item = {
                "summary_id": summary.id,
                "task_id": summary.task_id,
                "revision_number": summary.revision_number,
                "finality": summary.finality.value,
                "window_start": summary.statistics.window_start.isoformat(),
                "window_end": summary.statistics.window_end.isoformat(),
                "summary": narrative,
                "active_seconds": summary.statistics.active_seconds,
                "afk_seconds": summary.statistics.afk_seconds,
                "context_switch_count": summary.statistics.context_switch_count,
                "category_rule_version": summary.category_rule_version,
                "evidence_count": len(summary.evidence_refs),
                "model": summary.model,
                "prompt_version": summary.prompt_version,
            }
            candidate = [*items, item]
            envelope = {
                "data_classification": "untrusted_derived_activity_summaries",
                "instructions_allowed": False,
                "items": candidate,
                "redaction_count": redaction_count + count,
                "truncated": False,
            }
            if (
                len(json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                > 128 * 1024
            ):
                truncated = True
                break
            items = candidate
            redaction_count += count
        if len(summaries) > len(items):
            truncated = True
        return {
            "data_classification": "untrusted_derived_activity_summaries",
            "instructions_allowed": False,
            "items": items,
            "redaction_count": redaction_count,
            "truncated": truncated,
        }


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("activity time boundary must be an ISO datetime string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return require_aware(parsed)


def _window_arguments(arguments: dict[str, Any]) -> dict[str, datetime]:
    return {
        "start": _parse_datetime(arguments["start"]),
        "end": _parse_datetime(arguments["end"]),
    }
