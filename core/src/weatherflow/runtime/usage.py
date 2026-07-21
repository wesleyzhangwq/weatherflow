from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from weatherflow.runs import Run, RunStatus
from weatherflow.runtime.checkpoints import RunCheckpoint

RUN_USAGE_SCHEMA_VERSION = "run_usage_v1"


class RunModelRouteView(Protocol):
    provider: str
    model: str
    billing_origin: object


class CostStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class CostBudgetStatus(StrEnum):
    UNLIMITED = "unlimited"
    PENDING_USAGE = "pending_usage"
    WITHIN_BUDGET = "within_budget"
    EXCEEDED = "exceeded"
    UNKNOWN_COST = "unknown_cost"


class CostFailureReason(StrEnum):
    COST_UNKNOWN = "cost_unknown"
    COST_BUDGET_EXHAUSTED = "cost_budget_exhausted"


class RunUsage(BaseModel):
    """Credential-free, read-only projection of one durable Run's usage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["run_usage_v1"] = RUN_USAGE_SCHEMA_VERSION
    run_id: str
    provider: str | None
    model: str | None
    input_tokens: int = Field(ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    currency: Literal["USD", "CNY"] | None = None
    cost_scope: Literal["model_usage_only"] = "model_usage_only"
    billing_origin: str | None = Field(default=None, max_length=100)
    cost_status: CostStatus
    pricing_catalog_version: str | None
    step_count: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    timeout_seconds: int = Field(ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    cost_budget_usage_percent: float | None = Field(default=None, ge=0)
    cost_budget_status: CostBudgetStatus
    cost_failure_reason: CostFailureReason | None = None


def project_run_usage(
    *,
    run: Run,
    checkpoint: RunCheckpoint | None,
    route: RunModelRouteView | None,
    now: datetime | None = None,
) -> RunUsage:
    """Project existing accounting state without mutating or estimating it."""

    state = checkpoint.state if checkpoint is not None else {}
    raw_usage = state.get("runtime_usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = _nonnegative_int(usage.get("input_tokens")) or 0
    cache_read_input_tokens = _nonnegative_int(usage.get("cache_read_input_tokens"))
    if cache_read_input_tokens is not None and cache_read_input_tokens > input_tokens:
        cache_read_input_tokens = None
    output_tokens = _nonnegative_int(usage.get("output_tokens")) or 0
    raw_cost_amount = _nonnegative_float(usage.get("cost_amount", usage.get("cost_usd")))
    raw_cost_usd = _nonnegative_float(usage.get("cost_usd"))
    raw_currency = usage.get("currency")
    currency = raw_currency if raw_currency in {"USD", "CNY"} else None
    billing_origin = _bounded_string(
        usage.get("billing_origin"), max_length=100
    ) or _route_billing_origin(route)
    cost_scope = usage.get("cost_scope")
    missing_required_cache_breakdown = (
        route is not None and route.provider == "minimax" and cache_read_input_tokens is None
    )
    missing_required_minimax_billing = (
        route is not None
        and route.provider == "minimax"
        and (billing_origin is None or currency is None or cost_scope != "model_usage_only")
    )
    cost_status = (
        CostStatus.KNOWN
        if usage.get("cost_status") == CostStatus.KNOWN.value
        and raw_cost_amount is not None
        and currency is not None
        and cost_scope == "model_usage_only"
        and not missing_required_cache_breakdown
        and not missing_required_minimax_billing
        else CostStatus.UNKNOWN
    )
    cost_amount = raw_cost_amount if cost_status is CostStatus.KNOWN else None
    cost_usd = (
        raw_cost_usd
        if cost_status is CostStatus.KNOWN and currency == "USD" and raw_cost_usd is not None
        else None
    )
    pricing_catalog_version = (
        _bounded_string(usage.get("pricing_catalog_version"), max_length=200)
        if cost_status is CostStatus.KNOWN
        else None
    )
    step_count = checkpoint.step_index if checkpoint is not None else 0
    budget_status, budget_percent = _budget_projection(
        max_cost_usd=run.budget.max_cost_usd,
        cost_status=cost_status,
        cost_usd=cost_usd,
        step_count=step_count,
    )
    end = run.updated_at if run.status in _TERMINAL_STATUSES else (now or datetime.now(UTC))
    elapsed_seconds = max(0.0, (end - run.created_at).total_seconds())
    return RunUsage(
        run_id=run.id,
        provider=route.provider if route is not None else None,
        model=route.model if route is not None else None,
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_amount=cost_amount,
        cost_usd=cost_usd,
        currency=currency if cost_status is CostStatus.KNOWN else None,
        cost_scope="model_usage_only",
        billing_origin=billing_origin,
        cost_status=cost_status,
        pricing_catalog_version=pricing_catalog_version,
        step_count=step_count,
        elapsed_seconds=round(elapsed_seconds, 3),
        timeout_seconds=run.budget.timeout_seconds,
        max_cost_usd=run.budget.max_cost_usd,
        cost_budget_usage_percent=budget_percent,
        cost_budget_status=budget_status,
        cost_failure_reason=_cost_failure_reason(run),
    )


_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


def _budget_projection(
    *,
    max_cost_usd: float | None,
    cost_status: CostStatus,
    cost_usd: float | None,
    step_count: int,
) -> tuple[CostBudgetStatus, float | None]:
    if max_cost_usd is None:
        return CostBudgetStatus.UNLIMITED, None
    if step_count == 0:
        return CostBudgetStatus.PENDING_USAGE, 0.0
    if cost_status is CostStatus.UNKNOWN or cost_usd is None:
        return CostBudgetStatus.UNKNOWN_COST, None
    if max_cost_usd == 0:
        return (
            (CostBudgetStatus.WITHIN_BUDGET, 0.0)
            if cost_usd == 0
            else (CostBudgetStatus.EXCEEDED, None)
        )
    percent = round(cost_usd / max_cost_usd * 100, 6)
    return (
        CostBudgetStatus.EXCEEDED if cost_usd > max_cost_usd else CostBudgetStatus.WITHIN_BUDGET,
        percent,
    )


def _cost_failure_reason(run: Run) -> CostFailureReason | None:
    if run.error_message == "run cost budget cannot be enforced: model cost is unknown":
        return CostFailureReason.COST_UNKNOWN
    if run.error_message == "run cost budget exhausted":
        return CostFailureReason.COST_BUDGET_EXHAUSTED
    return None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _nonnegative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    if result < 0:
        return None
    return result


def _bounded_string(value: object, *, max_length: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= max_length else None


def _route_billing_origin(route: RunModelRouteView | None) -> str | None:
    value = getattr(route, "billing_origin", None)
    if hasattr(value, "value"):
        value = value.value
    return _bounded_string(value, max_length=100)
