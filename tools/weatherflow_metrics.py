#!/usr/bin/env python3
"""Reproducible WeatherFlow v3 production-metrics benchmark.

This harness deliberately exercises the existing RuntimeContainer, SharedTurnLoop,
Action/Approval, frozen capability/model/connector routes, MCP management, and
macOS Seatbelt seams.  It does not add a second runtime or policy path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.capabilities import CapabilityCatalog, ToolEffect, ToolSpec
from weatherflow.capabilities.builtin import developer_tool_specs
from weatherflow.config import Settings
from weatherflow.connectors import (
    ConnectorAccount,
    ConnectorBinding,
    ConnectorKind,
)
from weatherflow.continuations import ProviderAssistantMessage
from weatherflow.extensions import CredentialRef, MappingCredentialStore
from weatherflow.mcp import (
    InMemoryMCPConnectionRepository,
    MCPInstallAuthorization,
    MCPManagedHealth,
    MCPManagementService,
    MCPWorkspaceContext,
)
from weatherflow.models import RunModelRoute
from weatherflow.models.pricing import (
    BillingOrigin,
    MINIMAX_CN_PAYGO_CATALOG_VERSION,
    MINIMAX_CN_PAYGO_SOURCE_URLS,
    MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
    MINIMAX_GLOBAL_PAYGO_SOURCE_URLS,
    MINIMAX_TOKEN_PLAN_SOURCE_URLS,
    resolve_token_price,
)
from weatherflow.runs import RunBudget, RunStatus, ToolMode
from weatherflow.runtime import (
    FinalTurn,
    LoopStatus,
    ModelCompletion,
    ModelRouteUnavailableError,
    ModelUsage,
    ToolCallTurn,
    ToolExecutionContext,
    ToolExecutionResult,
)
from weatherflow.sandbox import (
    MacOSSeatbeltSandbox,
    SandboxLimits,
    SandboxNetworkMode,
    SandboxRequest,
    SandboxUnavailableError,
)
from weatherflow.trust import ActionStatus, DecisionKind, SupervisedPolicy
from weatherflow.workspaces import Workspace

BENCHMARK_VERSION = "weatherflow-v3-production-metrics-v2"
RAW_SCHEMA_VERSION = "weatherflow_metrics_raw_v1"
SUMMARY_SCHEMA_VERSION = "weatherflow_metrics_summary_v1"
MANIFEST_SCHEMA_VERSION = "weatherflow_metrics_manifest_v1"
PRIVATE_CONTINUATION_MARKER = "benchmark-provider-private-payload"
CONTINUATION_KEY = bytes(range(32))
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_MODEL = "MiniMax-M2.7"
MODEL_CREDENTIAL = CredentialRef(provider="minimax", name="api_key")
CONNECTOR_CREDENTIAL = CredentialRef(provider="composio", name="project_api_key")

READ_TOOL = ToolSpec(
    tool_id="benchmark.read",
    description="Return one deterministic read-only benchmark value",
    input_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    output_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    effect=ToolEffect.OBSERVE,
    source="weatherflow-benchmark",
    source_version=BENCHMARK_VERSION,
)

EXTERNAL_TOOL = ToolSpec(
    tool_id="benchmark.external_write",
    description="Record one deterministic external-side-effect benchmark receipt",
    input_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    output_schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"external_id": {"type": "string"}},
        "required": ["external_id"],
        "additionalProperties": False,
    },
    effect=ToolEffect.EXTERNAL_WRITE,
    required_scopes=frozenset({"benchmark:external"}),
    source="weatherflow-benchmark",
    source_version=BENCHMARK_VERSION,
)

RECOVERY_CASES = (
    "run_created_not_started",
    "model_turn_checkpointed",
    "tool_call_persisted_before_observation",
    "waiting_approval",
    "encrypted_provider_continuation",
    "read_tool_succeeded_before_observation",
    "external_action_succeeded_before_observation",
    "external_action_executing_unknown",
    "corrupt_checkpoint",
)

ISOLATION_CASES = (
    "missing_required_scope",
    "tool_outside_frozen_snapshot",
    "workspace_outside_read",
    "workspace_outside_write",
    "offline_network",
    "loopback_only_network",
    "keychain_access",
    "unapproved_external_write",
    "install_requires_approval",
    "destructive_requires_approval",
    "mcp_allowlist_bypass",
    "sandbox_unavailable_fail_closed",
)

COST_CASES = (
    "minimax_global_paygo_usd_known",
    "minimax_cn_paygo_cny_known_usd_budget_unknown",
    "minimax_token_plan_cost_unknown",
    "unpriced_openai_cost_unknown",
)


class ExpectedCrash(RuntimeError):
    """A typed, value-free process-loss injection signal."""


class ScriptedModel:
    def __init__(
        self,
        turns: Sequence[Any],
        *,
        call_labels: Sequence[str] | None = None,
        shared_calls: list[str] | None = None,
        pricing_catalog_version: str | None = None,
        continuation_provider: str | None = None,
        continuation_model: str | None = None,
        continuation_validator: Callable[[Any], None] | None = None,
    ) -> None:
        self.turns = list(turns)
        self.call_labels = list(
            call_labels or [f"turn-{index}" for index in range(len(turns))]
        )
        self.shared_calls = shared_calls if shared_calls is not None else []
        self.pricing_catalog_version = pricing_catalog_version
        self.continuation_provider = continuation_provider
        self.continuation_model = continuation_model
        self.continuation_validator = continuation_validator

    async def complete(self, request):
        if not self.turns:
            self.shared_calls.append("__unexpected_model_attempt__")
            raise AssertionError("unexpected duplicate model call")
        label = self.call_labels.pop(0)
        self.shared_calls.append(label)
        if self.continuation_validator is not None:
            self.continuation_validator(request)
        return self.turns.pop(0)


class FrozenRouteResolver:
    """Resolve only when the immutable Run route matches the benchmark contract."""

    def __init__(
        self, repository, model: ScriptedModel, *, provider: str, model_name: str
    ):
        self.repository = repository
        self.model = model
        self.provider = provider
        self.model_name = model_name

    async def resolve(self, run_id: str):
        route = await self.repository.get(run_id)
        if route is None or (route.provider, route.model) != (
            self.provider,
            self.model_name,
        ):
            raise ModelRouteUnavailableError("frozen benchmark route mismatch")
        return self.model


class RecordingExecutor:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.calls: list[str] = []

    async def execute(self, tool, arguments, context):
        del arguments
        self.calls.append(f"{context.run_id}:{tool.tool_id}")
        return ToolExecutionResult(output=self.output)


class CrashBeforeDispatch:
    async def dispatch(self, request, tool_map):
        del request, tool_map
        raise ExpectedCrash("after_model_turn_before_tool_dispatch")


class CrashAfterDispatch:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def dispatch(self, request, tool_map):
        await self.delegate.dispatch(request, tool_map)
        raise ExpectedCrash("after_tool_observation_commit")


class CrashObservationCommitter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    async def record_observation(self, *args, **kwargs):
        del args, kwargs
        raise ExpectedCrash("after_tool_success_before_observation_commit")

    async def record_transient_observation(self, *args, **kwargs):
        return await self.delegate.record_transient_observation(*args, **kwargs)


class FakeMCPTransport:
    def __init__(self, tool_name: str = "surprise_write") -> None:
        self.tool_name = tool_name
        self.closed = False

    async def request(self, method, params=None):
        del params
        if method == "initialize":
            return {"serverInfo": {"name": "fixture", "version": "1"}}
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": self.tool_name,
                        "description": "Unexpected tool",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": False},
                    }
                ]
            }
        raise AssertionError(method)

    async def notify(self, method, params=None):
        del method, params

    async def close(self) -> None:
        self.closed = True


class FakeMCPInstaller:
    def __init__(self) -> None:
        self.calls = 0

    async def install(
        self, preset, *, internal_root: Path, approved_action_id: str
    ) -> Path:
        self.calls += 1
        if not approved_action_id:
            raise PermissionError("approved Action required")
        target = preset.installation_root(internal_root)
        executable = preset.executable_path(internal_root)
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("fixture", encoding="utf-8")
        return target

    def is_installed(self, preset, *, internal_root: Path) -> bool:
        return preset.executable_path(internal_root).is_file()


@dataclass(slots=True)
class RecoveryContext:
    root: Path
    model_calls: list[str]
    read_executor: RecordingExecutor
    external_executor: RecordingExecutor
    before_model_route: str
    before_snapshot_id: str
    before_connector_routes: str
    rebuild_latency_ms: float = 0.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    """Nearest-rank percentile, intentionally well-defined for small n."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int((percentile * len(ordered) + 0.999999999)))
    return round(ordered[min(rank, len(ordered)) - 1], 3)


def _duplicate_count(labels: Sequence[str]) -> int:
    return sum(max(0, count - 1) for count in Counter(labels).values())


async def _route_fingerprint(container: RuntimeContainer, run_id: str) -> str:
    route = await container.model_routes.get(run_id)
    if route is None:
        return "missing"
    return _json_hash(
        {
            "run_id": route.run_id,
            "workspace_id": route.workspace_id,
            "configuration_workspace_id": route.configuration_workspace_id,
            "provider": route.provider,
            "model": route.model,
            "base_url": route.base_url,
            "credential_ref": route.credential_ref.model_dump(mode="json")
            if route.credential_ref
            else None,
            "billing_origin": (
                route.billing_origin.value if route.billing_origin is not None else None
            ),
            "configuration_version": route.configuration_version,
            "bound_at": route.bound_at.isoformat(),
        }
    )


async def _connector_route_fingerprint(container: RuntimeContainer, run_id: str) -> str:
    async with container.database.connect() as connection:
        rows = await (
            await connection.execute(
                """
                SELECT workspace_id, connector, account_id, external_account_id, bound_at
                FROM run_connector_routes WHERE run_id = ? ORDER BY connector
                """,
                (run_id,),
            )
        ).fetchall()
    return _json_hash([dict(row) for row in rows])


async def _bind_model_route(
    container: RuntimeContainer,
    run_id: str,
    *,
    provider: str = "minimax",
    model_name: str = MINIMAX_MODEL,
    base_url: str = MINIMAX_BASE_URL,
    credential_ref: CredentialRef = MODEL_CREDENTIAL,
    billing_origin: BillingOrigin | None = BillingOrigin.MINIMAX_GLOBAL_PAYGO,
) -> None:
    run = await container.runs.get(run_id)
    if run is None:
        raise LookupError(run_id)
    route = RunModelRoute(
        run_id=run.id,
        workspace_id=run.workspace_id,
        configuration_workspace_id=run.workspace_id,
        provider=provider,
        model=model_name,
        base_url=base_url,
        credential_ref=credential_ref,
        billing_origin=billing_origin,
        configuration_version=0,
        bound_at=_utc_now(),
    )
    async with container.database.transaction() as connection:
        await container.model_routes.create_in(connection, route)


def _bind_resolver(
    container: RuntimeContainer,
    model: ScriptedModel,
    *,
    provider: str = "minimax",
    model_name: str = MINIMAX_MODEL,
) -> None:
    container.loop.model_resolver = FrozenRouteResolver(
        container.model_routes,
        model,
        provider=provider,
        model_name=model_name,
    )


async def _install_frozen_connector_identity(
    container: RuntimeContainer, workspace_id: str
) -> None:
    existing = await container.connector_repository.get_binding(
        workspace_id, ConnectorKind.GITHUB
    )
    if existing is not None:
        return
    account = ConnectorAccount.new(
        workspace_id=workspace_id,
        connector=ConnectorKind.GITHUB,
        external_account_id="benchmark-account",
        credential_ref=CONNECTOR_CREDENTIAL,
    ).activate(display_name="Benchmark")
    binding = ConnectorBinding.new(
        workspace_id=workspace_id,
        connector=ConnectorKind.GITHUB,
        account_id=account.id,
    )
    await container.connector_repository.save_account(account)
    await container.connector_repository.save_binding(binding)


async def _create_container(
    root: Path,
    model: ScriptedModel,
    *,
    catalog: CapabilityCatalog | None = None,
    provider_continuation_key: bytes | None = None,
) -> RuntimeContainer:
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=catalog
        if catalog is not None
        else CapabilityCatalog([READ_TOOL, EXTERNAL_TOOL]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=(
            provider_continuation_key
            if provider_continuation_key is not None
            else CONTINUATION_KEY
        ),
    )
    container.executors.register(
        "benchmark.read", RecordingExecutor({"value": "unused"})
    )
    container.executors.register(
        "benchmark.external_write", RecordingExecutor({"external_id": "unused"})
    )
    return container


async def _prepare_recovery(
    root: Path,
    model: ScriptedModel,
    *,
    tool_mode: ToolMode,
) -> tuple[RuntimeContainer, Any, RecoveryContext]:
    root.mkdir(parents=True, exist_ok=True)
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog([READ_TOOL, EXTERNAL_TOOL]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    read_executor = RecordingExecutor({"value": "durable-read"})
    external_executor = RecordingExecutor({"external_id": "effect-1"})
    container.executors.register(READ_TOOL.tool_id, read_executor)
    container.executors.register(EXTERNAL_TOOL.tool_id, external_executor)
    project = root / "benchmark-project"
    project.mkdir(parents=True, exist_ok=True)
    workspace = Workspace.new(
        name="Recovery benchmark",
        action_roots=[project],
        internal_root=root / "benchmark-internal",
        artifact_root=root / "benchmark-artifacts",
        granted_scopes={"benchmark:external"},
    )
    await container.workspaces.create(workspace)
    await _install_frozen_connector_identity(container, workspace.id)
    run, _ = await container.submit_run(
        user_intent="deterministic recovery benchmark",
        client_request_id=f"benchmark-{root.name}",
        workspace_id=workspace.id,
        tool_mode=tool_mode,
        execute=False,
    )
    await _bind_model_route(container, run.id)
    _bind_resolver(container, model)
    stored = await container.runs.get(run.id)
    if stored is None or stored.capability_snapshot_id is None:
        raise RuntimeError("benchmark Run has no frozen snapshot")
    connector_fingerprint = await _connector_route_fingerprint(container, run.id)
    if connector_fingerprint == _json_hash([]):
        raise RuntimeError("benchmark Run has no frozen connector identity")
    context = RecoveryContext(
        root=root,
        model_calls=model.shared_calls,
        read_executor=read_executor,
        external_executor=external_executor,
        before_model_route=await _route_fingerprint(container, run.id),
        before_snapshot_id=stored.capability_snapshot_id,
        before_connector_routes=connector_fingerprint,
    )
    return container, run, context


async def _rebuild_recovery(
    context: RecoveryContext,
    model: ScriptedModel,
) -> RuntimeContainer:
    started = time.perf_counter()
    rebuilt = await RuntimeContainer.create(
        Settings(data_dir=context.root),
        model=model,
        catalog=CapabilityCatalog([READ_TOOL, EXTERNAL_TOOL]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    rebuilt.executors.register(READ_TOOL.tool_id, context.read_executor)
    rebuilt.executors.register(EXTERNAL_TOOL.tool_id, context.external_executor)
    _bind_resolver(rebuilt, model)
    context.rebuild_latency_ms = (time.perf_counter() - started) * 1000
    return rebuilt


async def _recovery_invariants(
    rebuilt: RuntimeContainer,
    run_id: str,
    context: RecoveryContext,
) -> dict[str, bool]:
    run = await rebuilt.runs.get(run_id)
    return {
        "model_route_preserved": (
            await _route_fingerprint(rebuilt, run_id) == context.before_model_route
        ),
        "capability_snapshot_preserved": (
            run is not None and run.capability_snapshot_id == context.before_snapshot_id
        ),
        "connector_routes_preserved": (
            await _connector_route_fingerprint(rebuilt, run_id)
            == context.before_connector_routes
        ),
    }


def _recovery_row(
    *,
    case_id: str,
    sample_index: int,
    passed: bool,
    latency_ms: float,
    model_calls: Sequence[str],
    read_calls: int,
    external_calls: int,
    needs_review_expected: bool,
    needs_review_correct: bool,
    quarantine_expected: bool,
    quarantine_correct: bool,
    invariants: dict[str, bool],
    evidence: str,
    rebuild_latency_ms: float,
) -> dict[str, Any]:
    expected_model_calls = {
        "run_created_not_started": 1,
        "model_turn_checkpointed": 1,
        "tool_call_persisted_before_observation": 2,
        "waiting_approval": 2,
        "encrypted_provider_continuation": 2,
        "read_tool_succeeded_before_observation": 2,
        "external_action_succeeded_before_observation": 2,
        "external_action_executing_unknown": 1,
        "corrupt_checkpoint": 0,
    }[case_id]
    actual_model_calls = len(model_calls)
    return {
        "schema_version": RAW_SCHEMA_VERSION,
        "category": "recovery",
        "case_id": case_id,
        "sample_index": sample_index,
        "status": "passed" if passed else "failed",
        "resume_latency_ms": round(latency_ms, 3),
        "rebuild_latency_ms": round(rebuild_latency_ms, 3),
        "rebuild_plus_resume_latency_ms": round(rebuild_latency_ms + latency_ms, 3),
        "actual_model_call_count": actual_model_calls,
        "expected_model_call_count": expected_model_calls,
        "duplicate_model_calls": max(0, actual_model_calls - expected_model_calls),
        "actual_read_tool_call_count": read_calls,
        "actual_external_tool_call_count": external_calls,
        "duplicate_tool_calls": max(0, read_calls - 1) + max(0, external_calls - 1),
        "duplicate_external_side_effects": max(0, external_calls - 1),
        "needs_review_expected": needs_review_expected,
        "needs_review_correct": needs_review_correct,
        "quarantine_expected": quarantine_expected,
        "quarantine_correct": quarantine_correct,
        **invariants,
        "evidence": evidence,
    }


async def _case_run_created(root: Path, sample_index: int) -> dict[str, Any]:
    calls: list[str] = []
    model = ScriptedModel(
        [FinalTurn(content="recovered")], call_labels=["final"], shared_calls=calls
    )
    first, run, context = await _prepare_recovery(root, model, tool_mode=ToolMode.ASK)
    await first.close()
    rebuilt_model = ScriptedModel(
        [FinalTurn(content="recovered")], call_labels=["final"], shared_calls=calls
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = outcome.status is LoopStatus.SUCCEEDED and all(invariants.values())
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[0],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=0,
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="queued Run rebuilt and completed through SharedTurnLoop",
    )


async def _case_model_turn_checkpointed(
    root: Path, sample_index: int
) -> dict[str, Any]:
    calls: list[str] = []
    model = ScriptedModel(
        [FinalTurn(content="durable final")], call_labels=["final"], shared_calls=calls
    )
    first, run, context = await _prepare_recovery(root, model, tool_mode=ToolMode.ASK)

    async def crash_final(run_value, checkpoint, content):
        del run_value, checkpoint, content
        raise ExpectedCrash("after_final_turn_checkpoint")

    first.loop._commit_final = crash_final
    try:
        await first.resume_run(run.id)
    except ExpectedCrash:
        pass
    checkpoint = await first.checkpoints.get(run.id)
    pending_final = bool(
        checkpoint and checkpoint.state.get("pending_turn", {}).get("kind") == "final"
    )
    await first.close()
    rebuilt = await _rebuild_recovery(context, ScriptedModel([], shared_calls=calls))
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        pending_final
        and outcome.status is LoopStatus.SUCCEEDED
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[1],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=0,
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="pending final turn committed without another model call",
    )


async def _case_tool_call_persisted(root: Path, sample_index: int) -> dict[str, Any]:
    calls: list[str] = []
    first_model = ScriptedModel(
        [ToolCallTurn(call_id="read-1", tool_id=READ_TOOL.tool_id, arguments={})],
        call_labels=["read-turn"],
        shared_calls=calls,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.ASK
    )
    first.loop.tool_dispatcher = CrashBeforeDispatch()
    try:
        await first.resume_run(run.id)
    except ExpectedCrash:
        pass
    checkpoint = await first.checkpoints.get(run.id)
    pending_tool = bool(
        checkpoint
        and checkpoint.state.get("pending_turn", {}).get("tool_id") == READ_TOOL.tool_id
    )
    await first.close()
    rebuilt_model = ScriptedModel(
        [FinalTurn(content="read recovered")], call_labels=["final"], shared_calls=calls
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        pending_tool
        and outcome.status is LoopStatus.SUCCEEDED
        and len(context.read_executor.calls) == 1
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[2],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=len(context.read_executor.calls),
        external_calls=0,
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="frozen pending tool turn executed once after rebuild",
    )


async def _case_waiting_approval(root: Path, sample_index: int) -> dict[str, Any]:
    calls: list[str] = []
    first_model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="external-1", tool_id=EXTERNAL_TOOL.tool_id, arguments={}
            )
        ],
        call_labels=["external-turn"],
        shared_calls=calls,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.BYPASS
    )
    waiting = await first.resume_run(run.id)
    waiting_identity = (waiting.action_id, waiting.approval_id)
    await first.close()
    rebuilt_model = ScriptedModel(
        [FinalTurn(content="approved recovery")],
        call_labels=["final"],
        shared_calls=calls,
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    recovered_waiting = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    stable_identity = waiting_identity == (
        recovered_waiting.action_id,
        recovered_waiting.approval_id,
    )
    no_execution_before_approval = len(context.external_executor.calls) == 0
    approval = await rebuilt.approvals.get(recovered_waiting.approval_id or "")
    if approval is None:
        raise RuntimeError("approval was not recovered")
    await rebuilt.approval_coordinator.decide(
        approval_id=approval.id,
        expected_version=approval.version,
        approved=True,
        decided_by="user",
    )
    completed = await rebuilt.resume_run(run.id)
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        recovered_waiting.status is LoopStatus.WAITING_APPROVAL
        and stable_identity
        and no_execution_before_approval
        and completed.status is LoopStatus.SUCCEEDED
        and len(context.external_executor.calls) == 1
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[3],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=len(context.external_executor.calls),
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="approval identity survived rebuild; execution waited for explicit approval",
    )


async def _case_provider_continuation(root: Path, sample_index: int) -> dict[str, Any]:
    calls: list[str] = []
    completion = ModelCompletion(
        turn=ToolCallTurn(
            call_id="continuation-1", tool_id=READ_TOOL.tool_id, arguments={}
        ),
        continuation=ProviderAssistantMessage(
            provider="minimax",
            model=MINIMAX_MODEL,
            payload={
                "role": "assistant",
                "content": None,
                "reasoning_details": [{"text": PRIVATE_CONTINUATION_MARKER}],
                "tool_calls": [{"id": "continuation-1"}],
            },
        ),
    )
    first_model = ScriptedModel(
        [completion],
        call_labels=["continuation-turn"],
        shared_calls=calls,
        continuation_provider="minimax",
        continuation_model=MINIMAX_MODEL,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.ASK
    )
    first.loop.tool_dispatcher = CrashAfterDispatch(first.loop.tool_dispatcher)
    try:
        await first.resume_run(run.id)
    except ExpectedCrash:
        pass
    checkpoint = await first.checkpoints.get(run.id)
    checkpoint_private = bool(
        checkpoint and PRIVATE_CONTINUATION_MARKER in checkpoint.model_dump_json()
    )
    async with first.database.connect() as connection:
        table_names = [
            row["name"]
            for row in await (
                await connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name != 'provider_continuations'"
                )
            ).fetchall()
        ]
        ordinary_rows: list[Any] = []
        for table_name in table_names:
            ordinary_rows.extend(
                await (
                    await connection.execute(f'SELECT * FROM "{table_name}"')
                ).fetchall()
            )
        continuation_count = (
            await (
                await connection.execute(
                    "SELECT COUNT(*) FROM provider_continuations WHERE run_id = ?",
                    (run.id,),
                )
            ).fetchone()
        )[0]
    ordinary_private = PRIVATE_CONTINUATION_MARKER in repr(ordinary_rows)
    await first.close()

    observed_continuation = False

    def validate_continuation(request) -> None:
        nonlocal observed_continuation
        observed_continuation = bool(
            request.provider_continuations
            and request.provider_continuations[0].payload["reasoning_details"][0][
                "text"
            ]
            == PRIVATE_CONTINUATION_MARKER
        )

    rebuilt_model = ScriptedModel(
        [FinalTurn(content="continuation recovered")],
        call_labels=["final"],
        shared_calls=calls,
        continuation_provider="minimax",
        continuation_model=MINIMAX_MODEL,
        continuation_validator=validate_continuation,
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    async with rebuilt.database.connect() as connection:
        remaining = (
            await (
                await connection.execute(
                    "SELECT COUNT(*) FROM provider_continuations WHERE run_id = ?",
                    (run.id,),
                )
            ).fetchone()
        )[0]
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        not checkpoint_private
        and not ordinary_private
        and continuation_count == 1
        and observed_continuation
        and remaining == 0
        and outcome.status is LoopStatus.SUCCEEDED
        and len(context.read_executor.calls) == 1
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[4],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=len(context.read_executor.calls),
        external_calls=0,
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="encrypted continuation restored, absent from ordinary state, deleted at terminal",
    )


async def _case_read_succeeded_before_observation(
    root: Path, sample_index: int
) -> dict[str, Any]:
    calls: list[str] = []
    first_model = ScriptedModel(
        [ToolCallTurn(call_id="read-replay", tool_id=READ_TOOL.tool_id, arguments={})],
        call_labels=["read-turn"],
        shared_calls=calls,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.ASK
    )
    first.loop.tool_dispatcher.committer = CrashObservationCommitter(
        first.loop.tool_dispatcher.committer
    )
    try:
        await first.resume_run(run.id)
    except ExpectedCrash:
        pass
    called_before_rebuild = len(context.read_executor.calls) == 1
    await first.close()
    rebuilt_model = ScriptedModel(
        [FinalTurn(content="safe replay recovered")],
        call_labels=["final"],
        shared_calls=calls,
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        called_before_rebuild
        and outcome.status is LoopStatus.SUCCEEDED
        and len(context.read_executor.calls) == 2
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[5],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=len(context.read_executor.calls),
        external_calls=0,
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="read-only tool safely replayed after success without durable observation",
    )


async def _case_external_succeeded_before_observation(
    root: Path, sample_index: int
) -> dict[str, Any]:
    calls: list[str] = []
    first_model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="effect-recover", tool_id=EXTERNAL_TOOL.tool_id, arguments={}
            )
        ],
        call_labels=["external-turn"],
        shared_calls=calls,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.BYPASS
    )
    waiting = await first.resume_run(run.id)
    approval = await first.approvals.get(waiting.approval_id or "")
    if approval is None:
        raise RuntimeError("approval was not created")
    await first.approval_coordinator.decide(
        approval_id=approval.id,
        expected_version=approval.version,
        approved=True,
        decided_by="user",
    )
    first.loop.tool_dispatcher.committer = CrashObservationCommitter(
        first.loop.tool_dispatcher.committer
    )
    try:
        await first.resume_run(run.id)
    except ExpectedCrash:
        pass
    action = await first.actions.get(waiting.action_id or "")
    persisted_success = bool(
        action and action.status is ActionStatus.SUCCEEDED and action.result
    )
    await first.close()
    rebuilt_model = ScriptedModel(
        [FinalTurn(content="effect receipt recovered")],
        call_labels=["final"],
        shared_calls=calls,
    )
    rebuilt = await _rebuild_recovery(context, rebuilt_model)
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = (
        persisted_success
        and outcome.status is LoopStatus.SUCCEEDED
        and len(context.external_executor.calls) == 1
        and all(invariants.values())
    )
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[6],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=len(context.external_executor.calls),
        needs_review_expected=False,
        needs_review_correct=True,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="persisted succeeded Action receipt recovered without repeating side effect",
    )


async def _case_external_executing_unknown(
    root: Path, sample_index: int
) -> dict[str, Any]:
    calls: list[str] = []
    first_model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="effect-unknown", tool_id=EXTERNAL_TOOL.tool_id, arguments={}
            )
        ],
        call_labels=["external-turn"],
        shared_calls=calls,
    )
    first, run, context = await _prepare_recovery(
        root, first_model, tool_mode=ToolMode.BYPASS
    )
    waiting = await first.resume_run(run.id)
    approval = await first.approvals.get(waiting.approval_id or "")
    if approval is None:
        raise RuntimeError("approval was not created")
    bundle = await first.approval_coordinator.decide(
        approval_id=approval.id,
        expected_version=approval.version,
        approved=True,
        decided_by="user",
    )
    async with first.database.transaction() as connection:
        executing = await first.actions.transition_in(
            connection,
            bundle.action.id,
            ActionStatus.EXECUTING,
            bundle.action.version,
        )
    await first.close()
    rebuilt = await _rebuild_recovery(context, ScriptedModel([], shared_calls=calls))
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    stored_action = await rebuilt.actions.get(executing.id)
    stored_run = await rebuilt.runs.get(run.id)
    needs_review_correct = bool(
        outcome.status is LoopStatus.NEEDS_REVIEW
        and stored_action
        and stored_action.status is ActionStatus.NEEDS_REVIEW
        and stored_run
        and stored_run.status is RunStatus.NEEDS_REVIEW
        and not context.external_executor.calls
    )
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = needs_review_correct and all(invariants.values())
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[7],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=0,
        needs_review_expected=True,
        needs_review_correct=needs_review_correct,
        quarantine_expected=False,
        quarantine_correct=True,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="EXECUTING side effect moved to NEEDS_REVIEW without executor replay",
    )


async def _case_corrupt_checkpoint(root: Path, sample_index: int) -> dict[str, Any]:
    calls: list[str] = []
    model = ScriptedModel([], shared_calls=calls)
    first, run, context = await _prepare_recovery(root, model, tool_mode=ToolMode.ASK)
    async with first.database.transaction() as connection:
        await connection.execute(
            "UPDATE checkpoints SET state = '{not-json' WHERE run_id = ?", (run.id,)
        )
    await first.close()
    rebuilt = await _rebuild_recovery(context, ScriptedModel([], shared_calls=calls))
    started = time.perf_counter()
    outcome = await rebuilt.resume_run(run.id)
    latency = (time.perf_counter() - started) * 1000
    async with rebuilt.database.connect() as connection:
        checkpoint_row = await (
            await connection.execute(
                "SELECT 1 FROM checkpoints WHERE run_id = ?", (run.id,)
            )
        ).fetchone()
        quarantine_row = await (
            await connection.execute(
                "SELECT reason, payload_sha256 FROM checkpoint_quarantine WHERE run_id = ?",
                (run.id,),
            )
        ).fetchone()
    timeline = await rebuilt.ledger.list_correlation(run.id, limit=1000)
    quarantine_correct = bool(
        checkpoint_row is None
        and quarantine_row
        and quarantine_row["reason"] == "checkpoint_validation_failed"
        and len(quarantine_row["payload_sha256"]) == 64
        and any(event.type == "runtime.checkpoint_quarantined" for event in timeline)
    )
    needs_review_correct = outcome.status is LoopStatus.NEEDS_REVIEW
    invariants = await _recovery_invariants(rebuilt, run.id, context)
    passed = quarantine_correct and needs_review_correct and all(invariants.values())
    await rebuilt.close()
    return _recovery_row(
        case_id=RECOVERY_CASES[8],
        sample_index=sample_index,
        passed=passed,
        latency_ms=latency,
        model_calls=calls,
        read_calls=0,
        external_calls=0,
        needs_review_expected=True,
        needs_review_correct=needs_review_correct,
        quarantine_expected=True,
        quarantine_correct=quarantine_correct,
        invariants=invariants,
        rebuild_latency_ms=context.rebuild_latency_ms,
        evidence="invalid checkpoint quarantined and Run moved to NEEDS_REVIEW",
    )


RECOVERY_RUNNERS: tuple[Callable[[Path, int], Awaitable[dict[str, Any]]], ...] = (
    _case_run_created,
    _case_model_turn_checkpointed,
    _case_tool_call_persisted,
    _case_waiting_approval,
    _case_provider_continuation,
    _case_read_succeeded_before_observation,
    _case_external_succeeded_before_observation,
    _case_external_executing_unknown,
    _case_corrupt_checkpoint,
)


async def _cost_workspace(
    container: RuntimeContainer,
    root: Path,
    *,
    max_cost_usd: float,
) -> Workspace:
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    workspace = Workspace.new(
        name="Cost benchmark",
        action_roots=[project],
        internal_root=root / "internal",
        artifact_root=root / "artifacts",
        default_budget=RunBudget(max_cost_usd=max_cost_usd),
    )
    await container.workspaces.create(workspace)
    return workspace


async def _cost_case_global_paygo(root: Path) -> dict[str, Any]:
    price = resolve_token_price(
        provider="minimax",
        model=MINIMAX_MODEL,
        billing_origin=BillingOrigin.MINIMAX_GLOBAL_PAYGO,
    )
    if price is None:
        raise RuntimeError("versioned MiniMax price is unavailable")
    input_tokens = 1_200
    cache_read_input_tokens = 0
    output_tokens = 300
    cost_amount = price.estimate(
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
    )
    if cost_amount is None:
        raise RuntimeError("MiniMax benchmark usage is outside the price tiers")
    model = ScriptedModel(
        [
            FinalTurn(
                content="known cost",
                usage=ModelUsage(
                    input_tokens=input_tokens,
                    cache_read_input_tokens=cache_read_input_tokens,
                    output_tokens=output_tokens,
                    cost_amount=cost_amount,
                    cost_usd=cost_amount,
                    currency=price.currency,
                    cost_scope=price.cost_scope,
                    billing_origin=price.billing_origin.value,
                ),
            )
        ],
        pricing_catalog_version=price.catalog_version,
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog(),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    workspace = await _cost_workspace(container, root, max_cost_usd=0.01)
    run, _ = await container.submit_run(
        user_intent="cost projection benchmark",
        client_request_id="known-cost",
        workspace_id=workspace.id,
        execute=False,
    )
    await _bind_model_route(container, run.id)
    _bind_resolver(container, model)
    outcome = await container.resume_run(run.id)
    usage = await container.run_usage(run.id)
    passed = bool(
        outcome.status is LoopStatus.SUCCEEDED
        and usage.input_tokens == input_tokens
        and usage.cache_read_input_tokens == cache_read_input_tokens
        and usage.output_tokens == output_tokens
        and usage.total_tokens == input_tokens + output_tokens
        and usage.cost_amount == cost_amount
        and usage.cost_usd == cost_amount
        and usage.currency == "USD"
        and usage.billing_origin == BillingOrigin.MINIMAX_GLOBAL_PAYGO.value
        and usage.cost_scope == "model_usage_only"
        and usage.cost_status.value == "known"
        and usage.pricing_catalog_version == price.catalog_version
        and usage.cost_budget_usage_percent is not None
    )
    row = {
        "schema_version": RAW_SCHEMA_VERSION,
        "category": "cost",
        "case_id": COST_CASES[0],
        "sample_index": 1,
        "status": "passed" if passed else "failed",
        "sample_type": "deterministic_provider_usage_fixture",
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost_amount": usage.cost_amount,
        "cost_usd": usage.cost_usd,
        "currency": usage.currency,
        "cost_scope": usage.cost_scope,
        "billing_origin": usage.billing_origin,
        "cost_status": usage.cost_status.value,
        "pricing_catalog_version": usage.pricing_catalog_version,
        "max_cost_usd": usage.max_cost_usd,
        "cost_budget_usage_percent": usage.cost_budget_usage_percent,
        "cost_budget_status": usage.cost_budget_status.value,
        "cost_failure_reason": (
            usage.cost_failure_reason.value
            if usage.cost_failure_reason is not None
            else None
        ),
        "evidence": "SharedTurnLoop persisted deterministic provider-shaped usage and projected it by Run",
    }
    await container.close()
    return row


async def _cost_case_cn_paygo(root: Path) -> dict[str, Any]:
    price = resolve_token_price(
        provider="minimax",
        model=MINIMAX_MODEL,
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
    )
    if price is None:
        raise RuntimeError("versioned mainland MiniMax price is unavailable")
    input_tokens = 1_200
    cache_read_input_tokens = 0
    output_tokens = 300
    cost_amount = price.estimate(
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
    )
    if cost_amount is None:
        raise RuntimeError("mainland MiniMax benchmark usage is outside the price tiers")
    model = ScriptedModel(
        [
            FinalTurn(
                content="known CNY cost",
                usage=ModelUsage(
                    input_tokens=input_tokens,
                    cache_read_input_tokens=cache_read_input_tokens,
                    output_tokens=output_tokens,
                    cost_amount=cost_amount,
                    cost_usd=None,
                    currency=price.currency,
                    cost_scope=price.cost_scope,
                    billing_origin=price.billing_origin.value,
                ),
            )
        ],
        pricing_catalog_version=price.catalog_version,
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog(),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    workspace = await _cost_workspace(container, root, max_cost_usd=0.01)
    run, _ = await container.submit_run(
        user_intent="CNY cost projection benchmark",
        client_request_id="cn-known-cost",
        workspace_id=workspace.id,
        execute=False,
    )
    await _bind_model_route(
        container,
        run.id,
        billing_origin=BillingOrigin.MINIMAX_CN_PAYGO,
    )
    _bind_resolver(container, model)
    outcome = await container.resume_run(run.id)
    usage = await container.run_usage(run.id)
    passed = bool(
        outcome.status is LoopStatus.FAILED
        and usage.cost_status.value == "known"
        and usage.cost_amount == cost_amount
        and usage.cost_usd is None
        and usage.currency == "CNY"
        and usage.billing_origin == BillingOrigin.MINIMAX_CN_PAYGO.value
        and usage.pricing_catalog_version == price.catalog_version
        and usage.cost_budget_status.value == "unknown_cost"
        and usage.cost_failure_reason == "cost_unknown"
    )
    row = _cost_row(usage, case_id=COST_CASES[1], passed=passed)
    row.update(
        sample_type="deterministic_cn_paygo_usage_fixture",
        evidence="official mainland CNY catalog remained CNY; finite USD budget failed closed without FX",
    )
    await container.close()
    return row


async def _cost_case_token_plan(root: Path) -> dict[str, Any]:
    model = ScriptedModel(
        [
            FinalTurn(
                content="Token Plan usage",
                usage=ModelUsage(
                    input_tokens=800,
                    cache_read_input_tokens=0,
                    output_tokens=100,
                    billing_origin=BillingOrigin.MINIMAX_CN_TOKEN_PLAN.value,
                ),
            )
        ],
        pricing_catalog_version=None,
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog(),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    workspace = await _cost_workspace(container, root, max_cost_usd=0.01)
    run, _ = await container.submit_run(
        user_intent="Token Plan fail-closed benchmark",
        client_request_id="token-plan-cost",
        workspace_id=workspace.id,
        execute=False,
    )
    await _bind_model_route(
        container,
        run.id,
        billing_origin=BillingOrigin.MINIMAX_CN_TOKEN_PLAN,
    )
    _bind_resolver(container, model)
    outcome = await container.resume_run(run.id)
    usage = await container.run_usage(run.id)
    passed = bool(
        outcome.status is LoopStatus.FAILED
        and usage.cost_status.value == "unknown"
        and usage.cost_amount is None
        and usage.cost_usd is None
        and usage.currency is None
        and usage.billing_origin == BillingOrigin.MINIMAX_CN_TOKEN_PLAN.value
        and usage.pricing_catalog_version is None
        and usage.cost_budget_status.value == "unknown_cost"
        and usage.cost_failure_reason == "cost_unknown"
    )
    row = _cost_row(usage, case_id=COST_CASES[2], passed=passed)
    row.update(
        sample_type="deterministic_token_plan_usage_fixture",
        evidence="Token Plan key type was explicit and never priced with the pay-as-you-go catalog",
    )
    await container.close()
    return row


def _cost_row(usage: Any, *, case_id: str, passed: bool) -> dict[str, Any]:
    return {
        "schema_version": RAW_SCHEMA_VERSION,
        "category": "cost",
        "case_id": case_id,
        "sample_index": 1,
        "status": "passed" if passed else "failed",
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost_amount": usage.cost_amount,
        "cost_usd": usage.cost_usd,
        "currency": usage.currency,
        "cost_scope": usage.cost_scope,
        "billing_origin": usage.billing_origin,
        "cost_status": usage.cost_status.value,
        "pricing_catalog_version": usage.pricing_catalog_version,
        "max_cost_usd": usage.max_cost_usd,
        "cost_budget_usage_percent": usage.cost_budget_usage_percent,
        "cost_budget_status": usage.cost_budget_status.value,
        "cost_failure_reason": (
            usage.cost_failure_reason.value if usage.cost_failure_reason is not None else None
        ),
    }


async def _cost_case_unknown(root: Path) -> dict[str, Any]:
    model = ScriptedModel(
        [
            FinalTurn(
                content="unpriced response",
                usage=ModelUsage(input_tokens=800, output_tokens=100, cost_usd=None),
            )
        ],
        pricing_catalog_version=None,
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog(),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    workspace = await _cost_workspace(container, root, max_cost_usd=0.01)
    run, _ = await container.submit_run(
        user_intent="unknown cost fail-closed benchmark",
        client_request_id="unknown-cost",
        workspace_id=workspace.id,
        execute=False,
    )
    await _bind_model_route(
        container,
        run.id,
        provider="openai",
        model_name="gpt-unpriced-compatible",
        base_url="https://api.openai.com/v1",
        credential_ref=CredentialRef(provider="openai", name="api_key"),
        billing_origin=None,
    )
    _bind_resolver(
        container,
        model,
        provider="openai",
        model_name="gpt-unpriced-compatible",
    )
    outcome = await container.resume_run(run.id)
    usage = await container.run_usage(run.id)
    passed = bool(
        outcome.status is LoopStatus.FAILED
        and usage.cost_usd is None
        and usage.cost_status.value == "unknown"
        and usage.pricing_catalog_version is None
        and usage.cost_budget_usage_percent is None
        and usage.cost_budget_status.value == "unknown_cost"
        and usage.cost_failure_reason == "cost_unknown"
    )
    row = {
        "schema_version": RAW_SCHEMA_VERSION,
        "category": "cost",
        "case_id": COST_CASES[3],
        "sample_index": 1,
        "status": "passed" if passed else "failed",
        "sample_type": "deterministic_unpriced_provider_usage_fixture",
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost_amount": usage.cost_amount,
        "cost_usd": usage.cost_usd,
        "currency": usage.currency,
        "cost_scope": usage.cost_scope,
        "billing_origin": usage.billing_origin,
        "cost_status": usage.cost_status.value,
        "pricing_catalog_version": usage.pricing_catalog_version,
        "max_cost_usd": usage.max_cost_usd,
        "cost_budget_usage_percent": usage.cost_budget_usage_percent,
        "cost_budget_status": usage.cost_budget_status.value,
        "cost_failure_reason": (
            usage.cost_failure_reason.value
            if usage.cost_failure_reason is not None
            else None
        ),
        "evidence": "finite budget failed closed while unknown cost remained null, never zero",
    }
    await container.close()
    return row


async def run_cost_benchmark(root: Path) -> list[dict[str, Any]]:
    return [
        await _cost_case_global_paygo(root / "global-paygo"),
        await _cost_case_cn_paygo(root / "cn-paygo"),
        await _cost_case_token_plan(root / "token-plan"),
        await _cost_case_unknown(root / "unpriced"),
    ]


def _isolation_row(
    *,
    case_id: str,
    status: str,
    escape_success_count: int = 0,
    unauthorized_execution_count: int = 0,
    approval_bypass_count: int = 0,
    evidence: str,
    skip_reason: str | None = None,
    host_external_control_reachable: bool | None = None,
) -> dict[str, Any]:
    row = {
        "schema_version": RAW_SCHEMA_VERSION,
        "category": "isolation",
        "case_id": case_id,
        "sample_index": 1,
        "status": status,
        "escape_success_count": escape_success_count,
        "unauthorized_execution_count": unauthorized_execution_count,
        "approval_bypass_count": approval_bypass_count,
        "evidence": evidence,
        "skip_reason": skip_reason,
    }
    if host_external_control_reachable is not None:
        row["host_external_control_reachable"] = host_external_control_reachable
    return row


async def _isolation_missing_scope(root: Path) -> dict[str, Any]:
    workspace = Workspace.new(
        name="No scope",
        action_roots=[root / "project"],
        internal_root=root / "internal",
        artifact_root=root / "artifacts",
    )
    tool = READ_TOOL.model_copy(
        update={
            "tool_id": "benchmark.scoped_read",
            "required_scopes": frozenset({"benchmark:private"}),
        }
    )
    decision = SupervisedPolicy().evaluate(tool, workspace)
    passed = decision.kind is DecisionKind.DENY and decision.missing_scopes == {
        "benchmark:private"
    }
    return _isolation_row(
        case_id=ISOLATION_CASES[0],
        status="passed" if passed else "failed",
        unauthorized_execution_count=0,
        evidence="SupervisedPolicy denied a tool whose required scope was absent",
    )


async def _isolation_frozen_snapshot(root: Path) -> dict[str, Any]:
    calls: list[str] = []
    model = ScriptedModel(
        [
            ToolCallTurn(call_id="ghost", tool_id="benchmark.surprise", arguments={}),
            FinalTurn(content="snapshot denial observed"),
        ],
        call_labels=["ghost-turn", "final"],
        shared_calls=calls,
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog([READ_TOOL]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    run, _ = await container.submit_run(
        user_intent="attempt a tool outside the frozen snapshot",
        client_request_id="isolation-frozen-snapshot",
        execute=False,
    )
    surprise = RecordingExecutor({"value": "must-not-run"})
    container.executors.register("benchmark.surprise", surprise)
    await _bind_model_route(container, run.id)
    _bind_resolver(container, model)
    outcome = await container.resume_run(run.id)
    checkpoint = await container.checkpoints.get(run.id)
    observed_denial = bool(
        checkpoint
        and "is not in frozen capability snapshot" in checkpoint.model_dump_json()
    )
    passed = bool(
        outcome.status is LoopStatus.SUCCEEDED
        and observed_denial
        and not surprise.calls
    )
    await container.close()
    return _isolation_row(
        case_id=ISOLATION_CASES[1],
        status="passed" if passed else "failed",
        unauthorized_execution_count=len(surprise.calls),
        evidence="SharedTurnLoop converted an out-of-snapshot call into an observation",
    )


async def _developer_boundary_rows(root: Path) -> list[dict[str, Any]]:
    data_dir = root / "runtime"
    container = await RuntimeContainer.create(
        Settings(data_dir=data_dir),
        model=ScriptedModel([]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    workspace_root = Path(container.default_workspace.action_roots[0])
    workspace_root.mkdir(parents=True, exist_ok=True)
    outside = root / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    outside_secret = outside / "secret.txt"
    outside_secret.write_text("host-only-value", encoding="utf-8")
    outside_write = outside / "escaped.txt"
    executor = container.executors.require("developer.read_file")
    tools = {tool.tool_id: tool for tool in developer_tool_specs()}
    context = ToolExecutionContext(
        run_id="isolation-run",
        workspace_id=container.default_workspace.id,
    )

    read_denied = False
    try:
        await executor.execute(
            tools["developer.read_file"],
            {"path": str(outside_secret)},
            context,
        )
    except PermissionError:
        read_denied = True

    write_denied = False
    try:
        await executor.execute(
            tools["developer.write_file"],
            {"path": str(outside_write), "content": "escaped"},
            context,
        )
    except PermissionError:
        write_denied = True

    read_escape = 0 if read_denied else 1
    write_escape = 0 if write_denied and not outside_write.exists() else 1
    await container.close()
    return [
        _isolation_row(
            case_id=ISOLATION_CASES[2],
            status="passed" if read_escape == 0 else "failed",
            escape_success_count=read_escape,
            unauthorized_execution_count=read_escape,
            evidence="DeveloperExecutor rejected an absolute path outside action roots",
        ),
        _isolation_row(
            case_id=ISOLATION_CASES[3],
            status="passed" if write_escape == 0 else "failed",
            escape_success_count=write_escape,
            unauthorized_execution_count=write_escape,
            evidence="DeveloperExecutor rejected an outside write and created no file",
        ),
    ]


def _seatbelt_request(
    workspace: Path,
    argv: tuple[str, ...],
    *,
    network: SandboxNetworkMode = SandboxNetworkMode.OFFLINE,
    writable: bool = False,
    extra_readable: tuple[str, ...] = (),
) -> SandboxRequest:
    return SandboxRequest(
        argv=argv,
        cwd=str(workspace),
        readable_roots=(str(workspace), *extra_readable),
        writable_roots=(str(workspace),) if writable else (),
        environment={"PATH": "/usr/bin:/bin"},
        network=network,
        limits=SandboxLimits(
            wall_time_seconds=5,
            cpu_time_seconds=5,
            max_file_size_bytes=1024**2,
            max_open_files=64,
            max_output_bytes=4096,
        ),
    )


async def _seatbelt_network_row(
    root: Path,
    *,
    loopback: bool,
) -> dict[str, Any]:
    case_id = ISOLATION_CASES[5] if loopback else ISOLATION_CASES[4]
    workspace = root / ("loopback" if loopback else "offline")
    workspace.mkdir(parents=True, exist_ok=True)
    external_host = "1.1.1.1"
    external_port = 443
    host_external_control_reachable = await _host_tcp_reachable(
        external_host, external_port
    )
    accepted = asyncio.Event()

    async def accept_connection(_reader, writer) -> None:
        accepted.set()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(accept_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    probe = workspace / "network_probe.py"
    probe.write_text(
        "import socket, sys\n"
        "local_ok = False\n"
        "external_ok = False\n"
        "try:\n"
        "    c = socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.4)\n"
        "    c.close(); local_ok = True\n"
        "except OSError:\n"
        "    pass\n"
        "try:\n"
        "    c = socket.create_connection((sys.argv[3], int(sys.argv[4])), timeout=0.5)\n"
        "    c.close(); external_ok = True\n"
        "except OSError:\n"
        "    pass\n"
        "expected_local = sys.argv[2] == 'allow'\n"
        "raise SystemExit(0 if local_ok == expected_local and not external_ok else 1)\n",
        encoding="utf-8",
    )
    python = Path(os.path.realpath(sys.executable))
    request = _seatbelt_request(
        workspace,
        (
            str(python),
            str(probe),
            str(port),
            "allow" if loopback else "deny",
            external_host,
            str(external_port),
        ),
        network=(
            SandboxNetworkMode.LOOPBACK if loopback else SandboxNetworkMode.OFFLINE
        ),
        extra_readable=(str(python.parent.parent),),
    )
    try:
        result = await MacOSSeatbeltSandbox().execute(request)
        if loopback:
            try:
                await asyncio.wait_for(accepted.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        server.close()
        await server.wait_closed()
    passed = (
        host_external_control_reachable
        and result.returncode == 0
        and accepted.is_set() is loopback
    )
    escape = 0 if passed else 1
    return _isolation_row(
        case_id=case_id,
        status="passed" if passed else "failed",
        escape_success_count=escape,
        unauthorized_execution_count=escape,
        evidence=(
            (
                "host reached 1.1.1.1:443; Seatbelt allowed loopback while denying the same external target"
                if loopback
                else "host reached 1.1.1.1:443; Seatbelt denied both loopback and the same external target"
            )
            if host_external_control_reachable
            else "host positive control could not reach 1.1.1.1:443; external-denial claim is invalid"
        ),
        host_external_control_reachable=host_external_control_reachable,
    )


async def _host_tcp_reachable(host: str, port: int) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    await writer.wait_closed()
    return True


async def _seatbelt_keychain_row(root: Path) -> dict[str, Any]:
    workspace = root / "keychain"
    workspace.mkdir(parents=True, exist_ok=True)
    result = await MacOSSeatbeltSandbox().execute(
        _seatbelt_request(
            workspace,
            ("/usr/bin/security", "list-keychains"),
        )
    )
    passed = result.returncode != 0 and not result.stdout.strip()
    escape = 0 if passed else 1
    return _isolation_row(
        case_id=ISOLATION_CASES[6],
        status="passed" if passed else "failed",
        escape_success_count=escape,
        unauthorized_execution_count=escape,
        evidence="Seatbelt denied Keychain enumeration and returned no stdout",
    )


async def _unapproved_external_row(root: Path) -> dict[str, Any]:
    calls: list[str] = []
    model = ScriptedModel(
        [
            ToolCallTurn(
                call_id="unapproved", tool_id=EXTERNAL_TOOL.tool_id, arguments={}
            )
        ],
        shared_calls=calls,
    )
    container, run, context = await _prepare_recovery(
        root, model, tool_mode=ToolMode.BYPASS
    )
    outcome = await container.resume_run(run.id)
    passed = (
        outcome.status is LoopStatus.WAITING_APPROVAL
        and not context.external_executor.calls
    )
    bypass = len(context.external_executor.calls)
    await container.close()
    return _isolation_row(
        case_id=ISOLATION_CASES[7],
        status="passed" if passed else "failed",
        unauthorized_execution_count=bypass,
        approval_bypass_count=bypass,
        evidence="external write parked durably before executor invocation",
    )


async def _install_row(root: Path) -> dict[str, Any]:
    tool = ToolSpec(
        tool_id="benchmark.install",
        description="Install benchmark package",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        effect=ToolEffect.INSTALL,
        source="weatherflow-benchmark",
        source_version=BENCHMARK_VERSION,
    )
    workspace = Workspace.new(
        name="Install policy",
        action_roots=[root / "project"],
        internal_root=root / "internal",
        artifact_root=root / "artifacts",
    )
    decision = SupervisedPolicy().evaluate(tool, workspace)
    installer = FakeMCPInstaller()
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=installer,
        transport_factory=lambda argv: FakeMCPTransport(),
    )
    project = root / "mcp-project"
    project.mkdir(parents=True, exist_ok=True)
    mcp_workspace = MCPWorkspaceContext(
        workspace_id="install-workspace",
        internal_root=root / "mcp-internal",
        action_roots=(project,),
    )
    denied = False
    try:
        await service.install(
            "filesystem",
            workspace=mcp_workspace,
            authorization=MCPInstallAuthorization(approved_action_id=""),
        )
    except PermissionError:
        denied = True
    await service.close()
    passed = decision.kind is DecisionKind.APPROVE and denied and installer.calls == 0
    bypass = 0 if passed else 1
    return _isolation_row(
        case_id=ISOLATION_CASES[8],
        status="passed" if passed else "failed",
        unauthorized_execution_count=installer.calls,
        approval_bypass_count=bypass,
        evidence="install policy required approval and MCP installer was not invoked",
    )


async def _destructive_row(root: Path) -> dict[str, Any]:
    tool = ToolSpec(
        tool_id="benchmark.destructive",
        description="Destructive benchmark operation",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        effect=ToolEffect.DESTRUCTIVE,
        source="weatherflow-benchmark",
        source_version=BENCHMARK_VERSION,
    )
    model = ScriptedModel(
        [ToolCallTurn(call_id="destructive", tool_id=tool.tool_id, arguments={})]
    )
    container = await RuntimeContainer.create(
        Settings(data_dir=root),
        model=model,
        catalog=CapabilityCatalog([tool]),
        credential_store=MappingCredentialStore({}),
        provider_continuation_key=CONTINUATION_KEY,
    )
    executor = RecordingExecutor({"deleted": True})
    container.executors.register(tool.tool_id, executor)
    run, _ = await container.submit_run(
        user_intent="attempt destructive operation",
        client_request_id="isolation-destructive",
        tool_mode=ToolMode.BYPASS,
        execute=False,
    )
    await _bind_model_route(container, run.id)
    _bind_resolver(container, model)
    outcome = await container.resume_run(run.id)
    passed = outcome.status is LoopStatus.WAITING_APPROVAL and not executor.calls
    bypass = len(executor.calls)
    await container.close()
    return _isolation_row(
        case_id=ISOLATION_CASES[9],
        status="passed" if passed else "failed",
        unauthorized_execution_count=bypass,
        approval_bypass_count=bypass,
        evidence="destructive operation parked for approval before executor invocation",
    )


async def _mcp_allowlist_row(root: Path) -> dict[str, Any]:
    installer = FakeMCPInstaller()
    service = MCPManagementService(
        repository=InMemoryMCPConnectionRepository(),
        package_installer=installer,
        transport_factory=lambda argv: FakeMCPTransport(tool_name="surprise_write"),
    )
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    workspace = MCPWorkspaceContext(
        workspace_id="mcp-allowlist",
        internal_root=root / "internal",
        action_roots=(project,),
    )
    await service.install(
        "filesystem",
        workspace=workspace,
        authorization=MCPInstallAuthorization(approved_action_id="action-approved"),
    )
    status = await service.enable("filesystem", workspace=workspace)
    active = service.active_tools(workspace.workspace_id)
    passed = status.health is MCPManagedHealth.UNAVAILABLE and not active
    await service.close()
    return _isolation_row(
        case_id=ISOLATION_CASES[10],
        status="passed" if passed else "failed",
        unauthorized_execution_count=0 if passed else 1,
        evidence="unexpected MCP discovery failed closed and exposed no active tools",
    )


async def _sandbox_unavailable_row(root: Path) -> dict[str, Any]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    backend = MacOSSeatbeltSandbox(
        executable=root / "missing-sandbox-exec",
        dyld_profile=root / "missing-profile",
    )
    healthy = await backend.health_probe()
    denied = False
    try:
        await backend.execute(
            _seatbelt_request(workspace, ("/bin/echo", "must-not-run"))
        )
    except SandboxUnavailableError:
        denied = True
    passed = not healthy and denied
    return _isolation_row(
        case_id=ISOLATION_CASES[11],
        status="passed" if passed else "failed",
        unauthorized_execution_count=0 if passed else 1,
        evidence="missing Seatbelt backend raised before spawning a child process",
    )


async def run_isolation_benchmark(
    root: Path,
    *,
    include_real_seatbelt: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    seatbelt = MacOSSeatbeltSandbox()
    seatbelt_health = await seatbelt.health_probe() if include_real_seatbelt else False
    rows = [
        await _isolation_missing_scope(root / "scope"),
        await _isolation_frozen_snapshot(root / "snapshot"),
        *(await _developer_boundary_rows(root / "developer")),
    ]
    if include_real_seatbelt and seatbelt_health:
        rows.extend(
            [
                await _seatbelt_network_row(root / "seatbelt", loopback=False),
                await _seatbelt_network_row(root / "seatbelt", loopback=True),
                await _seatbelt_keychain_row(root / "seatbelt"),
            ]
        )
    else:
        reason = (
            "real Seatbelt health probe unavailable"
            if include_real_seatbelt
            else "real Seatbelt disabled for portable test run"
        )
        rows.extend(
            _isolation_row(
                case_id=case_id,
                status="skipped",
                evidence="real macOS Seatbelt integration was not claimed",
                skip_reason=reason,
            )
            for case_id in ISOLATION_CASES[4:7]
        )
    rows.extend(
        [
            await _unapproved_external_row(root / "external"),
            await _install_row(root / "install"),
            await _destructive_row(root / "destructive"),
            await _mcp_allowlist_row(root / "mcp"),
            await _sandbox_unavailable_row(root / "sandbox-unavailable"),
        ]
    )
    return rows, {
        "requested": include_real_seatbelt,
        "health_probe": seatbelt_health,
        "backend": seatbelt.backend_id,
        "nested_sandbox_marker": bool(os.environ.get("WF_SANDBOX_ACTIVE")),
    }


RECOVERY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "run_created_not_started": {
        "persistence_boundary": "Run, frozen capability snapshot, model route, and connector route exist; execution has not started",
        "assertions": "rebuilt RuntimeContainer completes the same Run with all frozen identities unchanged",
        "expected_model_calls": 1,
    },
    "model_turn_checkpointed": {
        "persistence_boundary": "final model turn is the durable pending_turn; terminal Run commit is faulted",
        "assertions": "rebuild commits the pending final without another model call",
        "expected_model_calls": 1,
    },
    "tool_call_persisted_before_observation": {
        "persistence_boundary": "tool call is pending in RunCheckpoint; dispatcher is faulted before execution",
        "assertions": "rebuild executes the frozen read tool once, records observation, and completes",
        "expected_model_calls": 2,
    },
    "waiting_approval": {
        "persistence_boundary": "Run is WAITING_APPROVAL with durable Action and Approval identities",
        "assertions": "rebuild returns the same identities, performs no write before decision, then executes once after approval",
        "expected_model_calls": 2,
    },
    "encrypted_provider_continuation": {
        "persistence_boundary": "encrypted provider continuation and tool observation are durable before the next model request",
        "assertions": "private payload is absent from ordinary checkpoint/tables, restored after rebuild, and deleted at terminal",
        "expected_model_calls": 2,
    },
    "read_tool_succeeded_before_observation": {
        "persistence_boundary": "read-only executor returned successfully; observation commit is faulted",
        "assertions": "rebuild safely replays the read and completes; one duplicate read call is reported",
        "expected_model_calls": 2,
    },
    "external_action_succeeded_before_observation": {
        "persistence_boundary": "external Action is SUCCEEDED with durable result; observation commit is faulted",
        "assertions": "rebuild recovers the receipt and never repeats the external side effect",
        "expected_model_calls": 2,
    },
    "external_action_executing_unknown": {
        "persistence_boundary": "approved external Action is EXECUTING with unknown result semantics",
        "assertions": "rebuild calls no executor and moves both Action and Run to NEEDS_REVIEW",
        "expected_model_calls": 1,
    },
    "corrupt_checkpoint": {
        "persistence_boundary": "RunCheckpoint state contains malformed persisted JSON",
        "assertions": "rebuild removes the active row, stores hash/reason in quarantine, emits event, and requires review",
        "expected_model_calls": 0,
    },
}

ISOLATION_DEFINITIONS: dict[str, str] = {
    "missing_required_scope": "SupervisedPolicy DENY; no executor path is reached",
    "tool_outside_frozen_snapshot": "SharedTurnLoop observes a frozen-snapshot miss; surprise executor stays at zero",
    "workspace_outside_read": "DeveloperExecutor rejects an absolute read outside Workspace action roots",
    "workspace_outside_write": "DeveloperExecutor rejects an outside write and creates no target",
    "offline_network": "real Seatbelt OFFLINE denies loopback and external egress",
    "loopback_only_network": "real Seatbelt LOOPBACK reaches the local server but denies external egress",
    "keychain_access": "real Seatbelt denies security list-keychains and exposes no stdout",
    "unapproved_external_write": "external Action parks in WAITING_APPROVAL before executor invocation",
    "install_requires_approval": "install policy returns APPROVE and MCP installer rejects an empty approved Action",
    "destructive_requires_approval": "destructive operation parks in WAITING_APPROVAL before executor invocation",
    "mcp_allowlist_bypass": "unexpected MCP tool discovery marks the connection unavailable and exposes no tools",
    "sandbox_unavailable_fail_closed": "missing Seatbelt backend raises SandboxUnavailableError before child creation",
}


async def run_benchmark_suite(
    work_root: Path,
    *,
    repetitions: int = 1,
    include_real_seatbelt: bool = True,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    work_root.mkdir(parents=True, exist_ok=True)
    recovery_rows: list[dict[str, Any]] = []
    for sample_index in range(1, repetitions + 1):
        for case_index, runner in enumerate(RECOVERY_RUNNERS):
            recovery_rows.append(
                await runner(
                    work_root
                    / "recovery"
                    / f"sample-{sample_index}"
                    / f"case-{case_index}",
                    sample_index,
                )
            )
    cost_rows = await run_cost_benchmark(work_root / "cost")
    isolation_rows, seatbelt = await run_isolation_benchmark(
        work_root / "isolation",
        include_real_seatbelt=include_real_seatbelt,
    )
    rows = [*recovery_rows, *cost_rows, *isolation_rows]
    return {
        "rows": rows,
        "summary": summarize(rows),
        "seatbelt": seatbelt,
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    recovery = [row for row in rows if row["category"] == "recovery"]
    isolation = [row for row in rows if row["category"] == "isolation"]
    cost = [row for row in rows if row["category"] == "cost"]
    executed_isolation = [row for row in isolation if row["status"] != "skipped"]
    skipped_isolation = [row for row in isolation if row["status"] == "skipped"]
    resume_latencies = [float(row["resume_latency_ms"]) for row in recovery]
    total_latencies = [float(row["rebuild_plus_resume_latency_ms"]) for row in recovery]
    expected_review = [row for row in recovery if row["needs_review_expected"]]
    expected_quarantine = [row for row in recovery if row["quarantine_expected"]]

    recovery_summary = {
        "sample_count": len(recovery),
        "case_count": len({row["case_id"] for row in recovery}),
        "recovery_success_count": sum(row["status"] == "passed" for row in recovery),
        "recovery_success_rate": (
            sum(row["status"] == "passed" for row in recovery) / len(recovery)
            if recovery
            else None
        ),
        "resume_latency_scope": "resume_run_only_excludes_RuntimeContainer_create",
        "resume_latency_ms": {
            "n": len(resume_latencies),
            "p50": _percentile(resume_latencies, 0.50),
            "p95": _percentile(resume_latencies, 0.95),
            "mean": round(mean(resume_latencies), 3) if resume_latencies else None,
        },
        "rebuild_plus_resume_latency_scope": "RuntimeContainer_create_plus_resume_run",
        "rebuild_plus_resume_latency_ms": {
            "n": len(total_latencies),
            "p50": _percentile(total_latencies, 0.50),
            "p95": _percentile(total_latencies, 0.95),
            "mean": round(mean(total_latencies), 3) if total_latencies else None,
        },
        "duplicate_model_calls": sum(row["duplicate_model_calls"] for row in recovery),
        "duplicate_tool_calls": sum(row["duplicate_tool_calls"] for row in recovery),
        "duplicate_external_side_effects": sum(
            row["duplicate_external_side_effects"] for row in recovery
        ),
        "safe_read_replay_count": sum(
            row["duplicate_tool_calls"]
            for row in recovery
            if row["case_id"] == "read_tool_succeeded_before_observation"
        ),
        "needs_review_correct_count": sum(
            row["needs_review_correct"] for row in expected_review
        ),
        "needs_review_expected_count": len(expected_review),
        "quarantine_correct_count": sum(
            row["quarantine_correct"] for row in expected_quarantine
        ),
        "quarantine_expected_count": len(expected_quarantine),
        "model_route_preserved_count": sum(
            row["model_route_preserved"] for row in recovery
        ),
        "capability_snapshot_preserved_count": sum(
            row["capability_snapshot_preserved"] for row in recovery
        ),
        "connector_routes_preserved_count": sum(
            row["connector_routes_preserved"] for row in recovery
        ),
    }
    isolation_summary = {
        "case_count": len(isolation),
        "executed_case_count": len(executed_isolation),
        "skipped_case_count": len(skipped_isolation),
        "skipped_cases": [
            {"case_id": row["case_id"], "reason": row["skip_reason"]}
            for row in skipped_isolation
        ],
        "isolation_case_pass_count": sum(
            row["status"] == "passed" for row in executed_isolation
        ),
        "isolation_case_pass_rate": (
            sum(row["status"] == "passed" for row in executed_isolation)
            / len(executed_isolation)
            if executed_isolation
            else None
        ),
        "escape_success_count": sum(row["escape_success_count"] for row in isolation),
        "unauthorized_execution_count": sum(
            row["unauthorized_execution_count"] for row in isolation
        ),
        "approval_bypass_count": sum(row["approval_bypass_count"] for row in isolation),
        "production_security_complete": len(skipped_isolation) == 0,
    }
    cost_summary = {
        "sample_count": len(cost),
        "passed_count": sum(row["status"] == "passed" for row in cost),
        "known_cost_sample_count": sum(row["cost_status"] == "known" for row in cost),
        "unknown_cost_sample_count": sum(
            row["cost_status"] == "unknown" for row in cost
        ),
        "samples": [
            {
                key: row[key]
                for key in (
                    "case_id",
                    "sample_type",
                    "provider",
                    "model",
                    "input_tokens",
                    "cache_read_input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cost_amount",
                    "cost_usd",
                    "currency",
                    "cost_scope",
                    "billing_origin",
                    "cost_status",
                    "pricing_catalog_version",
                    "max_cost_usd",
                    "cost_budget_usage_percent",
                    "cost_budget_status",
                    "cost_failure_reason",
                )
            }
            for row in cost
        ],
    }
    overall_passed = bool(
        recovery_summary["recovery_success_rate"] == 1.0
        and isolation_summary["isolation_case_pass_rate"] == 1.0
        and isolation_summary["skipped_case_count"] == 0
        and isolation_summary["escape_success_count"] == 0
        and isolation_summary["unauthorized_execution_count"] == 0
        and isolation_summary["approval_bypass_count"] == 0
        and cost_summary["passed_count"] == cost_summary["sample_count"]
    )
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "overall_passed": overall_passed,
        "recovery": recovery_summary,
        "isolation": isolation_summary,
        "cost_observability": cost_summary,
    }


def _git_metadata(repo_root: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return commit, dirty


def _require_clean_worktree(
    repo_root: Path,
    *,
    expected_commit: str | None = None,
) -> str:
    commit, dirty = _git_metadata(repo_root)
    if dirty:
        raise RuntimeError(
            "refusing to generate production metrics from a dirty worktree; "
            "commit or otherwise preserve the source state first"
        )
    if expected_commit is not None and commit != expected_commit:
        raise RuntimeError(
            "refusing to generate production metrics after the source commit "
            "changed during the benchmark"
        )
    return commit


def build_manifest(
    *,
    repo_root: Path,
    generated_at: datetime,
    rows: Sequence[dict[str, Any]],
    repetitions: int,
    seatbelt: dict[str, Any],
    command: str,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    if expected_commit is None:
        commit, dirty = _git_metadata(repo_root)
    else:
        commit = _require_clean_worktree(repo_root, expected_commit=expected_commit)
        dirty = False
    contract = {
        "benchmark_version": BENCHMARK_VERSION,
        "recovery": RECOVERY_DEFINITIONS,
        "isolation": ISOLATION_DEFINITIONS,
        "cost": COST_CASES,
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": generated_at.isoformat(),
        "git_commit": commit,
        "dirty": dirty,
        "dataset_hash": _json_hash(contract),
        "sample_count": len(rows),
        "recovery_repetitions": repetitions,
        "recovery_case_count": len(RECOVERY_CASES),
        "isolation_case_count": len(ISOLATION_CASES),
        "cost_case_count": len(COST_CASES),
        "concurrency": 1,
        "warmup_runs": 0,
        "timing": {
            "clock": "time.perf_counter_monotonic",
            "resume_latency_scope": "resume_run_only_excludes_RuntimeContainer_create",
            "rebuild_plus_resume_latency_scope": "RuntimeContainer_create_plus_resume_run",
            "percentile_method": "nearest_rank",
        },
        "models": [
            {
                "provider": "minimax",
                "model": MINIMAX_MODEL,
                "sample_type": "deterministic_provider_usage_fixture",
            },
            {
                "provider": "openai",
                "model": "gpt-unpriced-compatible",
                "sample_type": "deterministic_unpriced_provider_usage_fixture",
            },
        ],
        "pricing_catalogs": [
            {
                "billing_origin": BillingOrigin.MINIMAX_GLOBAL_PAYGO.value,
                "currency": "USD",
                "catalog_version": MINIMAX_GLOBAL_PAYGO_CATALOG_VERSION,
                "source_urls": list(MINIMAX_GLOBAL_PAYGO_SOURCE_URLS),
            },
            {
                "billing_origin": BillingOrigin.MINIMAX_CN_PAYGO.value,
                "currency": "CNY",
                "catalog_version": MINIMAX_CN_PAYGO_CATALOG_VERSION,
                "source_urls": list(MINIMAX_CN_PAYGO_SOURCE_URLS),
            },
        ],
        "non_paygo_billing_sources": list(MINIMAX_TOKEN_PLAN_SOURCE_URLS),
        "cost_scope": "model_usage_only",
        "external_api_calls": 0,
        "seatbelt": seatbelt,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "non_sensitive_config": {
            "run_timeout_seconds": RunBudget().timeout_seconds,
            "sandbox_probe_timeout_seconds": 5,
            "provider_continuations": "encrypted_test_fixture",
            "frozen_identity_checks": [
                "model_route",
                "connector_route",
                "capability_snapshot",
            ],
        },
        "command": command,
        "sample_definitions": {
            "recovery": RECOVERY_DEFINITIONS,
            "isolation": ISOLATION_DEFINITIONS,
            "cost": {
                COST_CASES[0]: "explicit global PayGo origin; official USD catalog and deterministic provider-shaped tokens",
                COST_CASES[1]: "explicit mainland PayGo origin; official CNY catalog remains CNY and a USD budget fails closed without FX",
                COST_CASES[2]: "explicit Token Plan origin; no PayGo token-price substitution and finite USD budget fails closed",
                COST_CASES[3]: "deterministic unpriced token fixture; finite budget must fail closed and cost remains null",
            },
        },
        "sensitive_data_policy": "no credentials, prompts, or provider-private continuation payloads in artifacts",
    }


def render_report(
    *,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    rows: Sequence[dict[str, Any]],
) -> str:
    recovery = summary["recovery"]
    isolation = summary["isolation"]
    cost = summary["cost_observability"]
    lines = [
        "# WeatherFlow v3 生产化指标报告",
        "",
        f"- Benchmark: `{BENCHMARK_VERSION}`",
        f"- Generated: `{manifest['generated_at']}`",
        f"- Git commit: `{manifest['git_commit']}`; dirty: `{str(manifest['dirty']).lower()}`",
        f"- Dataset hash: `{manifest['dataset_hash']}`",
        f"- Command: `{manifest['command']}`",
        "- External API calls: `0`（模型与故障均为确定性 fixture；不把 fixture 冒充线上流量）",
        "",
        "## 结论",
        "",
        f"- Overall: `{'PASS' if summary['overall_passed'] else 'FAIL'}`",
        f"- Recovery success: `{recovery['recovery_success_rate']:.2%}` ({recovery['recovery_success_count']}/{recovery['sample_count']})",
        f"- Resume latency: P50 `{recovery['resume_latency_ms']['p50']}` ms, P95 `{recovery['resume_latency_ms']['p95']}` ms, n=`{recovery['resume_latency_ms']['n']}`",
        f"- Rebuild + resume latency: P50 `{recovery['rebuild_plus_resume_latency_ms']['p50']}` ms, P95 `{recovery['rebuild_plus_resume_latency_ms']['p95']}` ms, n=`{recovery['rebuild_plus_resume_latency_ms']['n']}`",
        f"- Duplicate model calls: `{recovery['duplicate_model_calls']}`; duplicate tool calls: `{recovery['duplicate_tool_calls']}`; duplicate external side effects: `{recovery['duplicate_external_side_effects']}`",
        f"- Isolation pass: `{isolation['isolation_case_pass_rate']:.2%}` ({isolation['isolation_case_pass_count']}/{isolation['executed_case_count']}); skipped: `{isolation['skipped_case_count']}`",
        f"- Production-security complete: `{str(isolation['production_security_complete']).lower()}` (requires skipped=`0`)",
        f"- Escape / unauthorized execution / approval bypass: `{isolation['escape_success_count']}` / `{isolation['unauthorized_execution_count']}` / `{isolation['approval_bypass_count']}`",
        "",
        "`resume_latency_ms` 只测 `resume_run`；`rebuild_plus_resume_latency_ms` 同时包含 `RuntimeContainer.create`。P95 使用 nearest-rank，样本量 n 明示；小样本不表述为稳定生产 SLO。",
        "",
        "## 恢复矩阵",
        "",
        "| Case | 持久化边界与核心断言 | n | Pass | Resume P50/P95 ms | Dup model/tool/external |",
        "|---|---|---:|---:|---:|---:|",
    ]
    recovery_rows = [row for row in rows if row["category"] == "recovery"]
    for case_id in RECOVERY_CASES:
        case_rows = [row for row in recovery_rows if row["case_id"] == case_id]
        latencies = [row["resume_latency_ms"] for row in case_rows]
        definition = RECOVERY_DEFINITIONS[case_id]
        boundary = f"{definition['persistence_boundary']}; {definition['assertions']}"
        lines.append(
            f"| `{case_id}` | {boundary} | {len(case_rows)} | "
            f"{sum(row['status'] == 'passed' for row in case_rows)} | "
            f"{_percentile(latencies, 0.50)}/{_percentile(latencies, 0.95)} | "
            f"{sum(row['duplicate_model_calls'] for row in case_rows)}/"
            f"{sum(row['duplicate_tool_calls'] for row in case_rows)}/"
            f"{sum(row['duplicate_external_side_effects'] for row in case_rows)} |"
        )
    lines.extend(
        [
            "",
            "只读工具在“执行成功但 observation 未提交”的边界会安全重放，因此该场景明确报告 1 次 duplicate tool call/样本；这不是外部副作用重复。已成功外部 Action 使用持久化 receipt 恢复，外部副作用重复数目标与结果均为 0。EXECUTING 且结果未知的 Action 必须进入 NEEDS_REVIEW。",
            "",
            "## 权限隔离矩阵",
            "",
            "| Case | Result | Evidence |",
            "|---|---|---|",
        ]
    )
    for row in (item for item in rows if item["category"] == "isolation"):
        result = row["status"]
        if row["status"] == "skipped":
            result += f" ({row['skip_reason']})"
        lines.append(f"| `{row['case_id']}` | `{result}` | {row['evidence']} |")
    lines.extend(
        [
            "",
            "生产安全结论要求真实 Seatbelt 用例全部执行且 skipped=0；任何 skipped 都会令 Overall=FAIL。portable CI 可验证其余合同，但不能产出 production-security PASS。网络负例还要求宿主先能到达同一外部目标，否则不会把目标本身不可达误报成 Seatbelt 拦截。",
            "",
            "## 按 Run 成本可观测样本",
            "",
            "| Case | Provider/model | Billing origin | Tokens in/cache-read/out/total | Amount/currency | Cost USD | Status/catalog | Budget result |",
            "|---|---|---|---:|---:|---:|---|---|",
        ]
    )
    for item in cost["samples"]:
        lines.append(
            f"| `{item['case_id']}` | `{item['provider']}/{item['model']}` | "
            f"`{item['billing_origin'] or 'unconfirmed'}` | "
            f"{item['input_tokens']}/{item['cache_read_input_tokens'] if item['cache_read_input_tokens'] is not None else 'unknown'}/{item['output_tokens']}/{item['total_tokens']} | "
            f"{item['cost_amount'] if item['cost_amount'] is not None else 'unknown'} / `{item['currency'] or 'none'}` | "
            f"{item['cost_usd'] if item['cost_usd'] is not None else 'unknown'} | "
            f"`{item['cost_status']}` / `{item['pricing_catalog_version'] or 'none'}` | "
            f"`{item['cost_budget_status']}` / `{item['cost_failure_reason'] or 'none'}` |"
        )
    lines.extend(
        [
            "",
            "MiniMax pricing catalogs are independent by billing origin and currency: "
            + "; ".join(
                f"`{catalog['billing_origin']}` / `{catalog['currency']}` / `{catalog['catalog_version']}` ("
                + ", ".join(f"[{url}]({url})" for url in catalog["source_urls"])
                + ")"
                for catalog in manifest["pricing_catalogs"]
            ),
            "",
            "所有样本的 `cost_scope=model_usage_only`，只覆盖模型 token 用量，不代表税费、订阅费、Credits 或最终账单。MiniMax 样本使用明确 `cached_tokens=0` 的 deterministic provider-shaped fixture；它不是实付或线上观测成本。计费类型由冻结的 `billing_origin` 明示，绝不从 hostname 推断：全球 PayGo 保留 USD，中国 PayGo 保留 CNY 且不做 FX；Token Plan 或未确认类型保持 unknown。缺少缓存明细、目录或明确计费来源时也保持 unknown，有限 USD 预算继续 fail-closed；unknown 从未当作 0。样本均不调用外部 API。",
            "",
            "## 可复现性与边界",
            "",
            f"- Recovery repetitions: `{manifest['recovery_repetitions']}`; concurrency: `1`; warmup: `0`.",
            "- Raw evidence is one JSON object per case/sample in `raw_results.jsonl`; aggregate values are in `summary.json`.",
            "- Model, connector, and capability identities are compared before/after every RuntimeContainer rebuild using stable hashes or IDs.",
            "- The continuation case checks ordinary checkpoint and every non-continuation SQLite table for the private fixture marker, then verifies encrypted-row deletion at terminal.",
            "- This is a deterministic recovery/security benchmark, not a live-provider availability or paid-traffic benchmark.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _validate_public_artifacts(payloads: Sequence[str]) -> None:
    forbidden = (
        PRIVATE_CONTINUATION_MARKER,
        "sk-must-not",
        "provider-private-reasoning",
    )
    combined = "\n".join(payloads)
    leaked = [marker for marker in forbidden if marker in combined]
    if leaked:
        raise RuntimeError("sensitive benchmark fixture escaped into public artifacts")


def _allocate_output_dir(output_root: Path, generated_at: datetime) -> Path:
    stem = generated_at.strftime("%Y%m%dT%H%M%SZ")
    candidate = output_root / stem
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{stem}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def write_benchmark_artifacts(
    *,
    output_root: Path,
    repo_root: Path,
    suite: dict[str, Any],
    repetitions: int,
    command: str,
    generated_at: datetime | None = None,
    expected_commit: str | None = None,
) -> Path:
    observed_at = generated_at or _utc_now()
    rows = suite["rows"]
    summary = suite["summary"]
    manifest = build_manifest(
        repo_root=repo_root,
        generated_at=observed_at,
        rows=rows,
        repetitions=repetitions,
        seatbelt=suite["seatbelt"],
        command=command,
        expected_commit=expected_commit,
    )
    manifest_text = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    raw_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        for row in rows
    )
    summary_text = (
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    report_text = render_report(manifest=manifest, summary=summary, rows=rows)
    _validate_public_artifacts([manifest_text, raw_text, summary_text, report_text])
    output_dir = _allocate_output_dir(output_root, observed_at)
    _atomic_write(output_dir / "manifest.json", manifest_text)
    _atomic_write(output_dir / "raw_results.jsonl", raw_text)
    _atomic_write(output_dir / "summary.json", summary_text)
    _atomic_write(output_dir / "report.md", report_text)
    return output_dir


async def _main(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        source_commit = _require_clean_worktree(repo_root)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    output_root = Path(args.output_root).expanduser().resolve()
    command = (
        "uv run --package weatherflow-core --extra dev python "
        f"tools/weatherflow_metrics.py --repetitions {args.repetitions} "
        f"--output-root {output_root}"
    )
    if args.skip_real_seatbelt:
        command += " --skip-real-seatbelt"
    import tempfile

    with tempfile.TemporaryDirectory(prefix="weatherflow-metrics-") as temporary:
        suite = await run_benchmark_suite(
            Path(temporary),
            repetitions=args.repetitions,
            include_real_seatbelt=not args.skip_real_seatbelt,
        )
    try:
        _require_clean_worktree(repo_root, expected_commit=source_commit)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    output_dir = write_benchmark_artifacts(
        output_root=output_root,
        repo_root=repo_root,
        suite=suite,
        repetitions=args.repetitions,
        command=command,
        expected_commit=source_commit,
    )
    print(output_dir)
    return 0 if suite["summary"]["overall_passed"] else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--output-root",
        default=str(repo_root / "eval" / "results" / BENCHMARK_VERSION),
    )
    parser.add_argument(
        "--skip-real-seatbelt",
        action="store_true",
        help="mark real Seatbelt cases skipped (portable CI only)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
