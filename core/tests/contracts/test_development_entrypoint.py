import json
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_root_package_exposes_pnpm_live_desktop_entrypoint() -> None:
    package = json.loads((ROOT / "package.json").read_text())

    assert package["packageManager"].startswith("pnpm@")
    assert package["scripts"]["dev:app"] == "python3 tools/dev/run_app.py"
    launcher = (ROOT / "tools" / "dev" / "run_app.py").read_text()
    assert '"rustup", "which", "cargo"' in launcher
    assert '"productName": "WeatherFlow Dev"' in launcher
    assert '"identifier": "ai.weatherflow.desktop.dev"' in launcher
    assert '"devUrl": "http://localhost:1421"' in launcher
    assert '["lsof", "-tiTCP:8765", "-sTCP:LISTEN"]' in launcher
    assert "finally:" in launcher
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
    assert 'IDENTITY="${WF_DEV_SIGNING_IDENTITY:-WeatherFlow Dev Signer}"' in setup
    assert "set-key-partition-list" in setup


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
