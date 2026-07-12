import json
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_root_package_exposes_pnpm_live_desktop_entrypoint() -> None:
    package = json.loads((ROOT / "package.json").read_text())

    assert package["packageManager"].startswith("pnpm@")
    assert package["scripts"]["dev:app"] == "python3 tools/dev/run_app.py"
    launcher = (ROOT / "tools" / "dev" / "run_app.py").read_text()
    assert '"rustup", "which", "cargo"' in launcher
    assert '"--filter", "weatherflow-desktop", "exec", "tauri", "dev"' in launcher


def test_tauri_development_hooks_use_pnpm() -> None:
    configuration = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())

    assert configuration["build"]["beforeDevCommand"] == "pnpm dev"
    assert configuration["build"]["beforeBuildCommand"] == "pnpm build"
    vite_configuration = (ROOT / "desktop" / "vite.config.ts").read_text()
    assert "port: 1420" in vite_configuration
    assert "strictPort: true" in vite_configuration
