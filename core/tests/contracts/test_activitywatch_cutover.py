from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_activitywatch_is_the_only_raw_activity_fact_source() -> None:
    architecture = (ROOT / "weatherflow-architecture-v3.md").read_text(encoding="utf-8")
    design = (ROOT / "docs/superpowers/specs/2026-07-12-weatherflow-v3-design.md").read_text(
        encoding="utf-8"
    )

    assert "ActivityWatch is the sole raw activity fact source" in architecture
    assert "strictly read-only" in architecture
    assert "ActivityWatch is the sole raw activity fact source" in design
    assert "Asia/Shanghai" in design


def test_weatherflow_watchers_and_heartbeat_write_path_are_removed() -> None:
    api = (ROOT / "core/src/weatherflow/api/app.py").read_text(encoding="utf-8")
    desktop_app = (ROOT / "desktop/src/app.tsx").read_text(encoding="utf-8")
    tauri = (ROOT / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert '"/v1/activity/heartbeats"' not in api
    assert "useActivityMetadata" not in desktop_app
    assert "sample_activity_metadata" not in tauri
    assert "mod activity;" not in tauri
    assert not (ROOT / "desktop/browser-extension").exists()


def test_activitywatch_runtime_exposes_only_read_and_derived_state_contracts() -> None:
    activity_package = ROOT / "core/src/weatherflow/activity"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(activity_package.glob("*.py"))
    )

    assert "ActivityWatchReadClient" in source
    assert "ActivitySummaryTask" in source
    assert "ActivityHeartbeat" not in source
    assert "record_heartbeat" not in source
    assert "delete_range" not in source


def test_legacy_activity_metadata_is_not_a_rhythm_domain_signal() -> None:
    rhythm_models = (ROOT / "core/src/weatherflow/rhythm/models.py").read_text(encoding="utf-8")
    rhythm_estimator = (ROOT / "core/src/weatherflow/rhythm/estimator.py").read_text(
        encoding="utf-8"
    )
    assert "class ActivityMetadata" not in rhythm_models
    assert "ActivityMetadata" not in rhythm_estimator
