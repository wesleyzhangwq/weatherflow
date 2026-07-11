import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_cockpit_is_explicit_and_capsule_is_pure_input() -> None:
    capsule = (ROOT / "desktop/src/components/Capsule.tsx").read_text()
    companion = (ROOT / "desktop/src/components/Companion.tsx").read_text()
    native = (ROOT / "desktop/src/native.ts").read_text()

    assert "openCockpit" not in capsule
    assert "speech-bubble" not in companion
    assert "onOpenCapsule" in companion
    assert "open_cockpit" in native


def test_tauri_starts_only_companion_and_owns_window_lifecycle() -> None:
    config = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    rust = (ROOT / "desktop/src-tauri/src/lib.rs").read_text()

    assert config["app"]["windows"] == []
    assert '"companion", "companion"' in rust
    assert '"capsule", "capsule"' in rust
    assert '"cockpit", "cockpit"' in rust
    assert "open_cockpit" in rust


def test_native_activity_response_has_no_raw_content_fields() -> None:
    rust = (ROOT / "desktop/src-tauri/src/activity.rs").read_text()
    interface = (
        (ROOT / "desktop/src/activity.ts")
        .read_text()
        .split("export class ActivityAccumulator", maxsplit=1)[0]
    )

    assert "pub struct ActivitySample" in rust
    assert "idle_seconds" in rust and "category" in rust
    for forbidden in ("window_title", "keystrokes", "clipboard", "screenshot", "application_name"):
        assert forbidden not in interface


def test_daemon_supervisor_uses_ephemeral_port_and_memory_token() -> None:
    supervisor = (ROOT / "desktop/src-tauri/src/supervisor.rs").read_text()

    assert 'TcpListener::bind("127.0.0.1:0")' in supervisor
    assert 'env("WF_BRIDGE_TOKEN"' in supervisor
    assert "restart_delay" in supervisor
    assert "5_000" in supervisor
