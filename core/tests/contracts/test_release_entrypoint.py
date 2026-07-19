import importlib.util
import json
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]


def _load_release_module():
    path = ROOT / "tools" / "release" / "release_macos.py"
    spec = importlib.util.spec_from_file_location("weatherflow_release_macos", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_launcher():
    path = ROOT / "tools" / "release" / "run_release.py"
    spec = importlib.util.spec_from_file_location("weatherflow_release_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_app_smoke():
    path = ROOT / "tools" / "release" / "smoke_app.py"
    spec = importlib.util.spec_from_file_location("weatherflow_app_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_dependencies_use_the_pnpm_inventory_without_package_lock(
    tmp_path, monkeypatch
) -> None:
    release = _load_release_module()
    (tmp_path / "desktop" / "src-tauri").mkdir(parents=True)
    (tmp_path / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "anyio"\nversion = "4.0.0"\n'
    )
    (tmp_path / "desktop" / "src-tauri" / "Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "serde"\nversion = "1.0.0"\n'
    )
    inventory = [
        {
            "name": "weatherflow-desktop",
            "version": "3.0.0-alpha.1",
            "dependencies": {
                "react": {
                    "version": "19.2.0",
                    "dependencies": {"scheduler": {"version": "0.27.0"}},
                }
            },
            "devDependencies": {
                "vite": {"version": "7.3.0"},
            },
        }
    ]
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, *, cwd, text, capture_output, check):
        calls.append((command, cwd))
        return SimpleNamespace(stdout=json.dumps(inventory))

    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "TAURI", tmp_path / "desktop" / "src-tauri")
    monkeypatch.setattr(release.subprocess, "run", fake_run)

    components = release.dependencies()

    assert calls == [
        (
            [
                "pnpm",
                "list",
                "--filter",
                "weatherflow-desktop",
                "--depth",
                "Infinity",
                "--json",
            ],
            tmp_path,
        )
    ]
    assert not (tmp_path / "desktop" / "package-lock.json").exists()
    assert components == [
        {"ecosystem": "cargo", "name": "serde", "version": "1.0.0"},
        {
            "ecosystem": "npm",
            "license": "SEE_UPSTREAM",
            "name": "react",
            "version": "19.2.0",
        },
        {
            "ecosystem": "npm",
            "license": "SEE_UPSTREAM",
            "name": "scheduler",
            "version": "0.27.0",
        },
        {
            "ecosystem": "npm",
            "license": "SEE_UPSTREAM",
            "name": "vite",
            "version": "7.3.0",
        },
        {"ecosystem": "pypi", "name": "anyio", "version": "4.0.0"},
    ]


def test_make_release_targets_build_and_open_only_the_canonical_bundle() -> None:
    makefile = (ROOT / "Makefile").read_text()

    assert "RELEASE_APP := $(abspath release/macos/WeatherFlow.app)" in makefile
    release_block = makefile.split("release-app:", 1)[1].split("\n\n", 1)[0]
    assert "\tpython3 tools/release/release_macos.py" in release_block

    run_block = makefile.split("run-release: release-app", 1)[1].split("\n\n", 1)[0]
    assert '\ttest -d "$(RELEASE_APP)"' in run_block
    assert '\ttest -f "$(RELEASE_APP)/Contents/Info.plist"' in run_block
    assert '\ttest -d "$(RELEASE_APP)/Contents/MacOS"' in run_block
    assert "\tpython3 tools/release/run_release.py" in run_block
    assert "/private/tmp" not in run_block
    assert "open -a" not in run_block
    assert "open -b" not in run_block
    assert "\topen " not in run_block


def test_release_launcher_rejects_a_bundle_built_from_stale_sources(tmp_path, monkeypatch) -> None:
    launcher = _load_release_launcher()
    app = tmp_path / "release" / "macos" / "WeatherFlow.app"
    executable = app / "Contents" / "MacOS" / "weatherflow-desktop"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"binary")
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "ai.weatherflow.desktop",
                "CFBundleExecutable": "weatherflow-desktop",
            }
        )
    )
    status = app.parent / "release-status.json"
    status.write_text(json.dumps({"source_digest": "old-digest"}))
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "release_source_digest", lambda _root: "new-digest")

    with pytest.raises(SystemExit, match="stale"):
        launcher.validate_canonical_release()


def test_release_launcher_replaces_known_weatherflow_apps_only() -> None:
    launcher = _load_release_launcher()
    root = ROOT.resolve()

    assert launcher.is_weatherflow_gui_process(
        "/Users/tester/Projects/WeatherFlow/release/macos/"
        "WeatherFlow.app/Contents/MacOS/weatherflow-desktop"
    )
    assert launcher.is_weatherflow_gui_process(
        "/Applications/WeatherFlow.app/Contents/MacOS/weatherflow-desktop"
    )
    assert launcher.is_weatherflow_gui_process(
        "/tmp/WeatherFlow Dev.app/Contents/MacOS/weatherflow-desktop"
    )
    assert launcher.is_weatherflow_gui_process(
        str(root / "desktop/src-tauri/target/weatherflow-dev-signed/weatherflow-desktop"),
        cwd=str(root),
        root=root,
    )
    assert launcher.is_weatherflow_gui_process(
        str(root / "desktop/src-tauri/target/debug/weatherflow-desktop"),
        cwd=str(root / "desktop"),
        root=root,
    )
    assert launcher.is_weatherflow_gui_process(
        str(root / "desktop/src-tauri/target/debug/weatherflow-desktop") + " --flag",
        cwd=str(root / "desktop"),
        root=root,
    )
    assert not launcher.is_weatherflow_gui_process(
        "/Applications/Unrelated.app/Contents/MacOS/weatherflow-desktop"
    )
    assert not launcher.is_weatherflow_gui_process(
        "python inspector.py /Applications/WeatherFlow.app/Contents/MacOS/weatherflow-desktop"
    )
    assert not launcher.is_weatherflow_gui_process(
        "file " + str(root / "desktop/src-tauri/target/debug/weatherflow-desktop"),
        cwd=str(root),
        root=root,
    )
    assert not launcher.is_weatherflow_gui_process(
        "/Users/other/WeatherFlow/desktop/src-tauri/target/debug/weatherflow-desktop",
        cwd="/Users/other/WeatherFlow",
        root=root,
    )


def test_release_provenance_covers_tauri_permissions_and_forbids_stale_sidecars() -> None:
    release = _load_release_module()
    source = (ROOT / "tools" / "release" / "release_macos.py").read_text()

    assert Path("desktop/src-tauri/capabilities") in release.RELEASE_SOURCE_INPUTS
    assert "--skip-sidecar" not in source


def test_release_builder_rejects_sources_changed_during_the_build(monkeypatch) -> None:
    release = _load_release_module()
    monkeypatch.setattr(release, "release_source_digest", lambda _root: "changed")

    with pytest.raises(SystemExit, match="changed during the release build"):
        release.require_unchanged_release_sources(Path("/repo"), "initial")


def test_app_smoke_owns_and_cleans_the_full_gui_process_group() -> None:
    source = (ROOT / "tools" / "release" / "smoke_app.py").read_text()

    assert "start_new_session=True" in source
    assert "os.killpg(process.pid, signal.SIGTERM)" in source
    assert "os.killpg(process.pid, signal.SIGKILL)" in source
    assert source.index("terminate_process_group(process)") < source.index(
        "process.communicate(timeout=2)"
    )


def test_app_smoke_allows_loaded_macos_enough_time_to_start_the_sidecar() -> None:
    smoke = _load_app_smoke()

    assert smoke.SMOKE_STARTUP_TIMEOUT_SECONDS >= 30


def test_release_launcher_binds_provenance_to_both_bundle_executables(
    tmp_path, monkeypatch
) -> None:
    launcher = _load_release_launcher()
    app = tmp_path / "release" / "macos" / "WeatherFlow.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    gui = macos / "weatherflow-desktop"
    sidecar = macos / "weatherflow-core"
    gui.write_bytes(b"gui")
    sidecar.write_bytes(b"sidecar")
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "ai.weatherflow.desktop",
                "CFBundleExecutable": "weatherflow-desktop",
            }
        )
    )
    (app.parent / "release-status.json").write_text(
        json.dumps(
            {
                "source_digest": "source",
                "gui_sha256": "wrong",
                "sidecar_sha256": launcher.sha256(sidecar),
            }
        )
    )
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "release_source_digest", lambda _root: "source")

    with pytest.raises(SystemExit, match="bundle content"):
        launcher.validate_canonical_release()


def test_release_launcher_revalidates_after_stopping_before_open(tmp_path, monkeypatch) -> None:
    launcher = _load_release_launcher()
    app = tmp_path / "WeatherFlow.app"
    validations = 0
    commands: list[list[str]] = []

    def validate():
        nonlocal validations
        validations += 1
        if validations == 2:
            raise SystemExit("canonical WeatherFlow release is stale")
        return app

    monkeypatch.setattr(launcher, "validate_canonical_release", validate)
    monkeypatch.setattr(launcher, "stop_existing_weatherflow_apps", lambda: None)
    monkeypatch.setattr(launcher, "exclusive_release_lock", _null_context)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    with pytest.raises(SystemExit, match="stale"):
        launcher.main()

    assert validations == 2
    assert not any(command[0] == "open" for command in commands)


def test_release_publish_atomically_replaces_the_previous_canonical_directory(
    tmp_path,
) -> None:
    release = _load_release_module()
    output = tmp_path / "macos"
    staging = tmp_path / ".weatherflow-release-staging"
    output.mkdir()
    staging.mkdir()
    (output / "marker").write_text("old")
    (staging / "marker").write_text("new")

    release.publish_staged_release(staging, output)

    assert (output / "marker").read_text() == "new"
    assert not staging.exists()
    assert not (tmp_path / ".macos.previous").exists()


def test_release_builder_and_launcher_share_one_exclusive_lock() -> None:
    release = _load_release_module()
    launcher = _load_release_launcher()

    assert release.RELEASE_LOCK == launcher.RELEASE_LOCK


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


def test_adhoc_release_does_not_enable_hardened_runtime(tmp_path, monkeypatch) -> None:
    release = _load_release_module()
    commands: list[list[str]] = []

    def fake_subprocess_run(command, **_kwargs):
        assert command == ["security", "find-identity", "-v", "-p", "codesigning"]
        return SimpleNamespace(stdout="0 valid identities found")

    monkeypatch.setattr(release, "OUTPUT", tmp_path)
    monkeypatch.setattr(release.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(release, "run", lambda command, **_kwargs: commands.append(command))

    state = release.signing_state(tmp_path / "WeatherFlow.app", tmp_path / "WeatherFlow.dmg")

    assert state == "adhoc_unsigned_credentials_missing"
    codesign = next(command for command in commands if command[0] == "codesign")
    assert "--sign" in codesign and "-" in codesign
    assert "--deep" not in codesign
    assert "--options" not in codesign
    assert "runtime" not in codesign


def test_release_rechecks_the_signed_bundled_sidecar() -> None:
    source = (ROOT / "tools" / "release" / "release_macos.py").read_text()
    signing_offset = source.index("state = signing_state(app, dmg, output=STAGING)")
    signed_sidecar_offset = source.index("validate_bundled_sidecar(app)", signing_offset)

    assert signed_sidecar_offset > signing_offset


def test_release_app_smoke_retries_one_transient_macos_launch_failure(
    tmp_path, monkeypatch
) -> None:
    release = _load_release_module()
    app = tmp_path / "WeatherFlow.app"
    calls: list[list[str]] = []

    def flaky_run(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise release.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(release, "run", flaky_run)

    release.validate_app_smoke(app)

    expected = ["python3", "tools/release/smoke_app.py", str(app)]
    assert calls == [expected, expected]
