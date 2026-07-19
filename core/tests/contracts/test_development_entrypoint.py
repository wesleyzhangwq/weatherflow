import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]


def _load_development_launcher():
    path = ROOT / "tools" / "dev" / "run_app.py"
    spec = importlib.util.spec_from_file_location("weatherflow_development_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_package_exposes_pnpm_live_desktop_entrypoint() -> None:
    package = json.loads((ROOT / "package.json").read_text())

    assert package["packageManager"].startswith("pnpm@")
    assert package["scripts"]["dev:app"] == "python3 tools/dev/run_app.py"
    launcher = (ROOT / "tools" / "dev" / "run_app.py").read_text()
    assert '"rustup", "which", "cargo"' in launcher
    assert '"productName": "WeatherFlow Dev"' in launcher
    assert '"identifier": "ai.weatherflow.desktop.dev"' in launcher
    assert '"devUrl": "http://localhost:1421"' in launcher
    assert '["lsof", "-tiTCP:1421", "-sTCP:LISTEN"]' in launcher
    assert '["lsof", "-tiTCP:8765", "-sTCP:LISTEN"]' in launcher
    assert "finally:" in launcher
    assert "stop_stale_development_frontend(root)" in launcher
    assert "stop_stale_development_daemon(root)" in launcher
    assert (
        '"--desktop-bootstrap-stdin"' in (ROOT / "desktop/src-tauri/src/supervisor.rs").read_text()
    )
    assert '"--reload"' not in (ROOT / "desktop/src-tauri/src/supervisor.rs").read_text()


def test_desktop_development_uses_a_stable_local_codesigning_identity() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    launcher = (ROOT / "tools" / "dev" / "run_app.py").read_text()
    setup = (ROOT / "tools" / "dev" / "setup_dev_codesign.sh").read_text()

    assert package["scripts"]["dev:signing:setup"] == ("bash tools/dev/setup_dev_codesign.sh")
    assert 'environment["APPLE_SIGNING_IDENTITY"]' in launcher
    assert "WF_DEV_SIGNING_IDENTITY" in launcher
    assert "WeatherFlow Dev Signer" in launcher
    assert "CARGO_TARGET_" in launcher
    assert "run_signed_binary.sh" in launcher
    runner = (ROOT / "tools" / "dev" / "run_signed_binary.sh").read_text()
    assert "existing_signature_is_usable" in runner
    assert "weatherflow-dev-signed" in runner
    assert "reusing stable signed runtime" in runner
    assert "source.sha256" in runner
    assert 'IDENTITY="${WF_DEV_SIGNING_IDENTITY:-WeatherFlow Dev Signer}"' in setup
    assert "set-key-partition-list" in setup
    assert "codesign:" in setup


def test_development_launcher_replaces_every_known_weatherflow_gui_binary() -> None:
    launcher = _load_development_launcher()
    root = ROOT.resolve()

    assert launcher.is_stale_weatherflow_gui_process(
        "/Users/tester/Projects/WeatherFlow/.worktrees/weatherflow-v3/"
        "release/macos/WeatherFlow.app/Contents/MacOS/WeatherFlow",
        cwd="/",
        root=root,
    )
    assert launcher.is_stale_weatherflow_gui_process(
        "/Applications/WeatherFlow.app/Contents/MacOS/weatherflow-desktop",
        cwd="/",
        root=root,
    )
    assert launcher.is_stale_weatherflow_gui_process(
        str(root / "desktop/src-tauri/target/weatherflow-dev-signed/weatherflow-desktop"),
        cwd=str(root),
        root=root,
    )
    assert launcher.is_stale_weatherflow_gui_process(
        str(root / "desktop/src-tauri/target/weatherflow-dev-signed/weatherflow-desktop")
        + " --flag",
        cwd=str(root),
        root=root,
    )
    assert not launcher.is_stale_weatherflow_gui_process(
        "file " + str(root / "desktop/src-tauri/target/weatherflow-dev-signed/weatherflow-desktop"),
        cwd=str(root),
        root=root,
    )
    assert not launcher.is_stale_weatherflow_gui_process(
        "python inspector.py /Applications/WeatherFlow.app/Contents/MacOS/weatherflow-desktop",
        cwd=str(root),
        root=root,
    )
    assert not launcher.is_stale_weatherflow_gui_process(
        "/Applications/Unrelated.app/Contents/MacOS/Unrelated",
        cwd="/",
        root=root,
    )


def test_development_launcher_replaces_only_weatherflow_vite_listeners() -> None:
    launcher = _load_development_launcher()
    root = ROOT.resolve()
    vite = "node /repo/node_modules/vite/bin/vite.js --host 127.0.0.1"

    assert launcher.is_stale_development_frontend_process(
        vite,
        cwd=str(root / "desktop"),
        root=root,
    )
    assert launcher.is_stale_development_frontend_process(
        vite,
        cwd=str(root / ".worktrees/weatherflow-v3/desktop"),
        root=root,
    )
    assert not launcher.is_stale_development_frontend_process(
        vite,
        cwd="/Users/tester/Projects/AnotherApp",
        root=root,
    )
    assert not launcher.is_stale_development_frontend_process(
        "python -m http.server 1421",
        cwd=str(root),
        root=root,
    )


def test_development_launcher_rebuilds_a_sidecar_when_core_sources_change(tmp_path) -> None:
    launcher = _load_development_launcher()
    (tmp_path / "core/src/weatherflow").mkdir(parents=True)
    (tmp_path / "core/src/weatherflow/service.py").write_text("VERSION = 1\n")
    (tmp_path / "core/pyproject.toml").write_text("[project]\nname='weatherflow-core'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    (tmp_path / "tools/release").mkdir(parents=True)
    (tmp_path / "tools/release/build_sidecar.py").write_text("# builder\n")
    binary = tmp_path / "desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"sidecar")
    stamp = launcher.development_sidecar_stamp(tmp_path)
    stamp.parent.mkdir(parents=True)
    stamp.write_text(launcher.development_sidecar_digest(tmp_path))

    assert not launcher.development_sidecar_rebuild_required(tmp_path)
    (tmp_path / "core/src/weatherflow/service.py").write_text("VERSION = 2\n")
    assert launcher.development_sidecar_rebuild_required(tmp_path)


def test_tauri_development_hooks_use_pnpm() -> None:
    configuration = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())

    assert configuration["build"]["beforeDevCommand"] == "pnpm dev"
    assert configuration["build"]["beforeBuildCommand"] == "pnpm build"
    vite_configuration = (ROOT / "desktop" / "vite.config.ts").read_text()
    assert "port: 1421" in vite_configuration
    assert "strictPort: true" in vite_configuration
    supervisor = (ROOT / "desktop" / "src-tauri" / "src" / "supervisor.rs").read_text()
    assert "const DEVELOPMENT_PORT: u16 = 8765;" in supervisor
    bridge = (ROOT / "desktop" / "src" / "bridge.ts").read_text()
    assert "VITE_WEATHERFLOW_BRIDGE_URL" in bridge
    assert '?? "http://127.0.0.1:8765"' in bridge
    assert '"--desktop-bootstrap-stdin"' in supervisor
    assert '"--reload"' not in supervisor
    assert "DaemonChild::External" not in supervisor
    cli = (ROOT / "core" / "src" / "weatherflow" / "cli.py").read_text()
    assert "reload_dirs=" in cli
    assert "timeout_graceful_shutdown=2" in cli
