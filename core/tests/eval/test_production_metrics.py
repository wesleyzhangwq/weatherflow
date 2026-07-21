import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from tools.weatherflow_metrics import (  # noqa: E402
    BENCHMARK_VERSION,
    PRIVATE_CONTINUATION_MARKER,
    RECOVERY_CASES,
    run_benchmark_suite,
    write_benchmark_artifacts,
)


async def test_v3_production_metrics_are_reproducible_and_fail_closed(
    tmp_path: Path,
) -> None:
    suite = await run_benchmark_suite(
        tmp_path / "work",
        repetitions=1,
        include_real_seatbelt=False,
    )
    summary = suite["summary"]
    recovery = summary["recovery"]
    isolation = summary["isolation"]
    cost = summary["cost_observability"]

    # Portable CI deliberately skips the three genuine Seatbelt rows.  It can
    # validate the remaining contracts, but may not claim production-security PASS.
    assert summary["overall_passed"] is False
    assert recovery["sample_count"] == len(RECOVERY_CASES) == 9
    assert recovery["recovery_success_rate"] == 1.0
    assert recovery["resume_latency_ms"]["n"] == 9
    assert recovery["rebuild_plus_resume_latency_ms"]["n"] == 9
    assert recovery["duplicate_model_calls"] == 0
    assert recovery["duplicate_tool_calls"] == 1
    assert recovery["safe_read_replay_count"] == 1
    assert recovery["duplicate_external_side_effects"] == 0
    assert recovery["needs_review_correct_count"] == 2
    assert recovery["needs_review_expected_count"] == 2
    assert recovery["quarantine_correct_count"] == 1
    assert recovery["quarantine_expected_count"] == 1
    assert recovery["model_route_preserved_count"] == 9
    assert recovery["capability_snapshot_preserved_count"] == 9
    assert recovery["connector_routes_preserved_count"] == 9

    # Portable eval explicitly excludes genuine Seatbelt integration rows from
    # the denominator. The separately generated local report runs them when the
    # macOS health probe succeeds.
    assert isolation["case_count"] == 12
    assert isolation["executed_case_count"] == 9
    assert isolation["skipped_case_count"] == 3
    assert isolation["production_security_complete"] is False
    assert isolation["isolation_case_pass_rate"] == 1.0
    assert isolation["escape_success_count"] == 0
    assert isolation["unauthorized_execution_count"] == 0
    assert isolation["approval_bypass_count"] == 0

    assert cost["passed_count"] == cost["sample_count"] == 4
    global_paygo, cn_paygo, token_plan, unpriced = cost["samples"]
    assert global_paygo["cost_status"] == "known"
    assert global_paygo["model"] == "MiniMax-M2.7"
    assert global_paygo["cache_read_input_tokens"] == 0
    assert global_paygo["cost_amount"] == global_paygo["cost_usd"] == 0.00072
    assert global_paygo["currency"] == "USD"
    assert global_paygo["billing_origin"] == "minimax_global_paygo"
    assert global_paygo["cost_scope"] == "model_usage_only"
    assert global_paygo["pricing_catalog_version"] == "minimax-global-paygo-usd-2026-07-21"
    assert cn_paygo["cost_status"] == "known"
    assert cn_paygo["cost_amount"] == 0.00504
    assert cn_paygo["cost_usd"] is None
    assert cn_paygo["currency"] == "CNY"
    assert cn_paygo["billing_origin"] == "minimax_cn_paygo"
    assert cn_paygo["cost_budget_status"] == "unknown_cost"
    assert cn_paygo["cost_failure_reason"] == "cost_unknown"
    assert token_plan["cost_status"] == "unknown"
    assert token_plan["billing_origin"] == "minimax_cn_token_plan"
    assert token_plan["cost_amount"] is None and token_plan["currency"] is None
    assert token_plan["pricing_catalog_version"] is None
    assert unpriced["cost_status"] == "unknown"
    assert unpriced["cache_read_input_tokens"] is None
    assert unpriced["cost_amount"] is None and unpriced["cost_usd"] is None
    assert unpriced["pricing_catalog_version"] is None
    assert unpriced["cost_budget_usage_percent"] is None
    assert unpriced["cost_budget_status"] == "unknown_cost"
    assert unpriced["cost_failure_reason"] == "cost_unknown"

    output_dir = write_benchmark_artifacts(
        output_root=tmp_path / "results" / BENCHMARK_VERSION,
        repo_root=REPO_ROOT,
        suite=suite,
        repetitions=1,
        command="portable eval fixture",
        generated_at=datetime(2026, 7, 21, 0, 0, tzinfo=UTC),
    )
    expected_files = {
        "manifest.json",
        "raw_results.jsonl",
        "summary.json",
        "report.md",
    }
    assert {path.name for path in output_dir.iterdir()} == expected_files

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    persisted_summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    raw_rows = [
        json.loads(line)
        for line in (output_dir / "raw_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    public_artifacts = "\n".join(
        (output_dir / filename).read_text(encoding="utf-8") for filename in expected_files
    )
    assert manifest["benchmark_version"] == BENCHMARK_VERSION
    assert manifest["sample_count"] == len(raw_rows) == 25
    assert manifest["external_api_calls"] == 0
    assert manifest["timing"]["percentile_method"] == "nearest_rank"
    assert len(manifest["sample_definitions"]["recovery"]) == 9
    assert manifest["cost_case_count"] == 4
    catalog_identities = {
        (item["billing_origin"], item["currency"]) for item in manifest["pricing_catalogs"]
    }
    assert catalog_identities == {
        ("minimax_global_paygo", "USD"),
        ("minimax_cn_paygo", "CNY"),
    }
    assert persisted_summary == summary
    assert PRIVATE_CONTINUATION_MARKER not in public_artifacts


async def test_seatbelt_external_denial_requires_reachable_host_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.weatherflow_metrics as metrics

    async def host_unreachable(_host: str, _port: int) -> bool:
        return False

    class FakeSeatbelt:
        async def execute(self, _request):
            return SimpleNamespace(returncode=0)

    monkeypatch.setattr(metrics, "_host_tcp_reachable", host_unreachable)
    monkeypatch.setattr(metrics, "MacOSSeatbeltSandbox", FakeSeatbelt)

    row = await metrics._seatbelt_network_row(tmp_path, loopback=False)

    assert row["status"] == "failed"
    assert row["host_external_control_reachable"] is False
    assert "positive control" in row["evidence"]


async def test_production_metrics_cli_refuses_a_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import tools.weatherflow_metrics as metrics

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("dirty preflight must fail before the benchmark runs")

    monkeypatch.setattr(metrics, "_git_metadata", lambda _root: ("a" * 40, True))
    monkeypatch.setattr(metrics, "run_benchmark_suite", must_not_run)
    output_root = tmp_path / "must-not-exist"
    args = metrics.parse_args(
        [
            "--repetitions",
            "1",
            "--output-root",
            str(output_root),
            "--skip-real-seatbelt",
        ]
    )

    assert await metrics._main(args) == 2
    assert "dirty worktree" in capsys.readouterr().err
    assert not output_root.exists()


async def test_production_metrics_cli_rejects_a_commit_change_during_the_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import tools.weatherflow_metrics as metrics

    metadata = iter([("a" * 40, False), ("b" * 40, False)])

    async def completed_suite(*_args, **_kwargs):
        return {"summary": {"overall_passed": True}}

    monkeypatch.setattr(metrics, "_git_metadata", lambda _root: next(metadata))
    monkeypatch.setattr(metrics, "run_benchmark_suite", completed_suite)
    output_root = tmp_path / "must-not-exist"
    args = metrics.parse_args(
        [
            "--repetitions",
            "1",
            "--output-root",
            str(output_root),
            "--skip-real-seatbelt",
        ]
    )

    assert await metrics._main(args) == 2
    assert "source commit changed" in capsys.readouterr().err
    assert not output_root.exists()
