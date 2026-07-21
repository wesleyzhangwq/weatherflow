from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from weatherflow.runs import Run, RunBudget, RunStatus
from weatherflow.runtime import (
    CostBudgetStatus,
    CostFailureReason,
    CostStatus,
    RunCheckpoint,
    project_run_usage,
)


def test_run_usage_projects_known_cost_budget_and_terminal_elapsed() -> None:
    created_at = datetime(2026, 7, 21, 2, 0, tzinfo=UTC)
    run = Run.new(
        client_request_id="usage-known",
        user_intent="Measure this Run",
        workspace_id="workspace-1",
        budget=RunBudget(max_cost_usd=0.01, timeout_seconds=120),
    ).model_copy(
        update={
            "status": RunStatus.SUCCEEDED,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=12.3456),
        }
    )
    checkpoint = RunCheckpoint.new(run_id=run.id).model_copy(
        update={
            "step_index": 2,
            "state": {
                "runtime_usage": {
                    "input_tokens": 1_200,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 300,
                    "cost_amount": 0.00072,
                    "cost_usd": 0.00072,
                    "currency": "USD",
                    "cost_scope": "model_usage_only",
                    "billing_origin": "minimax_global_paygo",
                    "cost_status": "known",
                    "pricing_catalog_version": "minimax-global-paygo-usd-2026-07-21",
                }
            },
        }
    )

    usage = project_run_usage(
        run=run,
        checkpoint=checkpoint,
        route=SimpleNamespace(
            provider="minimax",
            model="MiniMax-M2.7",
            billing_origin="minimax_global_paygo",
        ),
        now=created_at + timedelta(days=1),
    )

    assert usage.schema_version == "run_usage_v1"
    assert (usage.provider, usage.model) == ("minimax", "MiniMax-M2.7")
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (1_200, 300, 1_500)
    assert usage.cache_read_input_tokens == 0
    assert usage.cost_status is CostStatus.KNOWN
    assert usage.cost_amount == 0.00072
    assert usage.cost_usd == 0.00072
    assert usage.currency == "USD"
    assert usage.cost_scope == "model_usage_only"
    assert usage.billing_origin == "minimax_global_paygo"
    assert usage.pricing_catalog_version == "minimax-global-paygo-usd-2026-07-21"
    assert usage.step_count == 2
    assert usage.elapsed_seconds == 12.346
    assert usage.timeout_seconds == 120
    assert usage.max_cost_usd == 0.01
    assert usage.cost_budget_usage_percent == 7.2
    assert usage.cost_budget_status is CostBudgetStatus.WITHIN_BUDGET
    assert usage.cost_failure_reason is None


def test_run_usage_keeps_unknown_cost_explicit_and_projects_fail_closed_reason() -> None:
    created_at = datetime(2026, 7, 21, 2, 0, tzinfo=UTC)
    run = Run.new(
        client_request_id="usage-unknown",
        user_intent="Use an unpriced model",
        workspace_id="workspace-1",
        budget=RunBudget(max_cost_usd=0.02, timeout_seconds=300),
    ).model_copy(
        update={
            "status": RunStatus.FAILED,
            "created_at": created_at,
            "updated_at": created_at + timedelta(seconds=5),
            "error_class": "RuntimeLimitError",
            "error_message": "run cost budget cannot be enforced: model cost is unknown",
        }
    )
    checkpoint = RunCheckpoint.new(run_id=run.id).model_copy(
        update={
            "step_index": 1,
            "state": {
                "runtime_usage": {
                    "input_tokens": 800,
                    "output_tokens": 100,
                    "cost_usd": None,
                    "cost_status": "unknown",
                    "pricing_catalog_version": "must-not-survive",
                }
            },
        }
    )

    usage = project_run_usage(
        run=run,
        checkpoint=checkpoint,
        route=SimpleNamespace(provider="openai", model="gpt-test"),
    )

    assert usage.total_tokens == 900
    assert usage.cost_status is CostStatus.UNKNOWN
    assert usage.cost_usd is None
    assert usage.pricing_catalog_version is None
    assert usage.cost_budget_usage_percent is None
    assert usage.cost_budget_status is CostBudgetStatus.UNKNOWN_COST
    assert usage.cost_failure_reason is CostFailureReason.COST_UNKNOWN


def test_run_usage_invalidates_legacy_minimax_cost_without_cache_breakdown() -> None:
    run = Run.new(
        client_request_id="usage-legacy-minimax",
        user_intent="Inspect legacy accounting",
        workspace_id="workspace-1",
        budget=RunBudget(max_cost_usd=0.01),
    )
    checkpoint = RunCheckpoint.new(run_id=run.id).model_copy(
        update={
            "step_index": 1,
            "state": {
                "runtime_usage": {
                    "input_tokens": 1_200,
                    "output_tokens": 300,
                    "cost_usd": 0.00072,
                    "cost_status": "known",
                    "pricing_catalog_version": "minimax-paygo-2026-07-14",
                }
            },
        }
    )

    usage = project_run_usage(
        run=run,
        checkpoint=checkpoint,
        route=SimpleNamespace(provider="minimax", model="MiniMax-M3"),
    )

    assert usage.cache_read_input_tokens is None
    assert usage.cost_status is CostStatus.UNKNOWN
    assert usage.cost_usd is None
    assert usage.pricing_catalog_version is None
    assert usage.cost_budget_status is CostBudgetStatus.UNKNOWN_COST


def test_run_usage_projects_pending_and_zero_budget_without_dividing_by_zero() -> None:
    run = Run.new(
        client_request_id="usage-pending",
        user_intent="Wait",
        workspace_id="workspace-1",
        budget=RunBudget(max_cost_usd=0),
    )

    pending = project_run_usage(
        run=run,
        checkpoint=None,
        route=None,
        now=run.created_at + timedelta(seconds=1),
    )
    exceeded = project_run_usage(
        run=run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "error_class": "RuntimeLimitError",
                "error_message": "run cost budget exhausted",
            }
        ),
        checkpoint=RunCheckpoint.new(run_id=run.id).model_copy(
            update={
                "step_index": 1,
                "state": {
                    "runtime_usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost_amount": 0.0001,
                        "cost_usd": 0.0001,
                        "currency": "USD",
                        "cost_scope": "model_usage_only",
                        "cost_status": "known",
                    }
                },
            }
        ),
        route=None,
    )

    assert pending.cost_budget_status is CostBudgetStatus.PENDING_USAGE
    assert pending.cost_budget_usage_percent == 0
    assert pending.provider is None and pending.model is None
    assert exceeded.cost_budget_status is CostBudgetStatus.EXCEEDED
    assert exceeded.cost_budget_usage_percent is None
    assert exceeded.cost_failure_reason is CostFailureReason.COST_BUDGET_EXHAUSTED
