from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_flagship_eval_helpers_are_not_shipped_in_the_runtime_package() -> None:
    runtime_eval = ROOT / "core/src/weatherflow/eval"
    assert not tuple(runtime_eval.glob("*.py"))
    assert (ROOT / "core/tests/eval/fixture.py").is_file()


def test_activity_summary_contracts_use_summary_language() -> None:
    activity = ROOT / "core/src/weatherflow/activity"
    assert not (activity / "inference.py").exists()
    assert (activity / "summarization.py").is_file()

    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(activity.glob("*.py")))
    assert "ActivityAnalysisRoute" not in source
    assert "ActivityAnalysisResult" not in source


def test_removed_rhythm_compatibility_interfaces_stay_removed() -> None:
    rhythm = ROOT / "core/src/weatherflow/rhythm"
    api = (ROOT / "core/src/weatherflow/api/app.py").read_text(encoding="utf-8")
    schemas = (ROOT / "core/src/weatherflow/api/schemas.py").read_text(encoding="utf-8")
    connector_tools = (ROOT / "core/src/weatherflow/connectors/tools.py").read_text(
        encoding="utf-8"
    )
    desktop_bridge = (ROOT / "desktop/src/bridge.ts").read_text(encoding="utf-8")
    tauri_lib = (ROOT / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    supervisor = (ROOT / "desktop/src-tauri/src/supervisor.rs").read_text(encoding="utf-8")

    assert not (rhythm / "insights.py").exists()
    assert "accept_remote_snapshot" not in (rhythm / "service.py").read_text(encoding="utf-8")
    assert "delete_activity_evidence" not in (rhythm / "service.py").read_text(encoding="utf-8")
    assert "expired_snapshot" not in (rhythm / "models.py").read_text(encoding="utf-8")
    assert '"/v1/rhythm/insights"' not in api
    assert '"/v1/watch/profile"' in api
    assert "ForbiddenActivityMetadataRequest" not in schemas
    assert "ActivityEvidenceView" not in schemas
    assert "composio_remote_actions" not in connector_tools
    assert "cancel(runId" not in desktop_bridge
    assert "rhythmInsights(" not in desktop_bridge
    assert "ingestSignal(" not in desktop_bridge
    assert "watchStatistics(" not in desktop_bridge
    assert "watchTimeline(" not in desktop_bridge
    assert "restart_daemon" not in tauri_lib
    assert "restart_daemon" not in supervisor


def test_historical_delivery_material_is_kept_in_git_history_only() -> None:
    assert not (ROOT / "docs/superpowers/plans").exists()
    assert not (ROOT / "docs/final-audit.md").exists()
    assert not (ROOT / "docs/research/2026-07-15-user-state-agent-landscape").exists()
    assert not (ROOT / "artifacts/design-qa").exists()
    assert not (ROOT / "design-qa.md").exists()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "P0 established" not in readme
    assert "Enable metadata" not in readme


def test_security_hardening_suite_is_not_run_twice() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    test_recipe = makefile.split("\ntest:\n", 1)[1].split("\neval:\n", 1)[0]
    assert "--ignore=core/tests/operations/test_hardening.py" in test_recipe
