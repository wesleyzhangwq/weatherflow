import json
from io import BytesIO

from weatherflow import __version__
from weatherflow.cli import build_parser, main


def test_version_command_prints_core_version(capsys) -> None:
    exit_code = main(["--version"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_serve_command_uses_settings_defaults(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("weatherflow.cli.uvicorn.run", fake_run)

    exit_code = main(["serve"])

    assert exit_code == 0
    assert captured == {
        "app": "weatherflow.api.app:app",
        "host": "127.0.0.1",
        "port": 8765,
        "reload": False,
        "reload_dirs": None,
        "timeout_graceful_shutdown": 2,
        "log_level": "info",
    }


def test_parser_requires_a_command_without_version() -> None:
    parser = build_parser()

    args = parser.parse_args(["serve", "--port", "9000", "--reload"])

    assert args.command == "serve"
    assert args.port == 9000
    assert args.reload is True


def test_minimax_configuration_parser_uses_current_safe_defaults() -> None:
    args = build_parser().parse_args(["configure-minimax", "--api-key-stdin"])

    assert args.command == "configure-minimax"
    assert args.model == "MiniMax-M3"
    assert args.base_url == "https://api.minimax.io/v1"
    assert args.api_key_stdin is True


def test_minimax_configuration_uses_hidden_prompt_and_redacted_output(monkeypatch, capsys) -> None:
    captured: dict[str, str] = {}

    class Store:
        def __init__(self) -> None:
            self.value = None

        def resolve(self, reference):
            return self.value

        def set(self, reference, secret):
            self.value = secret

        def delete(self, reference):
            self.value = None

    store = Store()

    class Configuration:
        def model_dump_json(self, **kwargs) -> str:
            assert kwargs == {"exclude": {"credential_ref"}}
            return '{"provider":"minimax","model":"MiniMax-M3"}'

    class Container:
        async def configure_minimax(self, **kwargs):
            captured.update(kwargs)
            return Configuration()

    async def create(settings, *, credential_store):
        assert credential_store is store
        return Container()

    monkeypatch.setattr("weatherflow.cli.RuntimeContainer.create", create)
    monkeypatch.setattr("weatherflow.cli.KeyringCredentialStore", lambda: store)
    monkeypatch.setattr("weatherflow.cli.getpass.getpass", lambda prompt: "hidden-key")

    exit_code = main(["configure-minimax"])

    assert exit_code == 0
    assert captured == {
        "model": "MiniMax-M3",
        "base_url": "https://api.minimax.io/v1",
    }
    assert store.value == "hidden-key"
    assert "hidden-key" not in capsys.readouterr().out


def test_desktop_serve_reads_private_bootstrap_from_stdin(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class Stdin:
        buffer = BytesIO(
            (
                '{"version":1,"bridge_token":"'
                + "a" * 64
                + '","credential_socket":"/tmp/weatherflow.sock","credential_token":"'
                + "b" * 64
                + '"}\n'
            ).encode()
        )

    async def create(settings, *, credential_store):
        captured["settings"] = settings
        captured["credential_store"] = credential_store
        return object()

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured["run"] = kwargs

    monkeypatch.setattr("weatherflow.cli.sys.stdin", Stdin())
    monkeypatch.setattr("weatherflow.cli.RuntimeContainer.create", create)
    monkeypatch.setattr("weatherflow.cli.create_app", lambda settings, container: "desktop-app")
    monkeypatch.setattr("weatherflow.cli.watch_parent_disconnect", lambda stream: None)
    monkeypatch.setattr("weatherflow.cli.uvicorn.run", fake_run)

    exit_code = main(
        [
            "--data-dir",
            str(tmp_path),
            "serve",
            "--desktop-bootstrap-stdin",
        ]
    )

    assert exit_code == 0
    assert captured["app"] == "desktop-app"
    assert captured["settings"].bridge_token == "a" * 64
    assert "token=<redacted>" in repr(captured["credential_store"])
    assert captured["run"] == {
        "host": "127.0.0.1",
        "port": 8765,
        "reload": False,
        "timeout_graceful_shutdown": 2,
        "log_level": "info",
    }


def test_run_and_status_commands_use_durable_data_dir(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--data-dir",
            str(tmp_path),
            "run",
            "Explain WeatherFlow",
            "--client-request-id",
            "request-1",
        ]
    )
    created = json.loads(capsys.readouterr().out)

    status_code = main(["--data-dir", str(tmp_path), "status", created["id"]])
    stored = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert status_code == 0
    assert stored["status"] == "waiting_user"
    assert stored["result_summary"] is None
    assert stored["error_class"] == "ModelConfigurationRequired"


def test_timeline_command_outputs_ordered_events(tmp_path, capsys) -> None:
    main(["--data-dir", str(tmp_path), "run", "Hello"])
    run = json.loads(capsys.readouterr().out)

    exit_code = main(["--data-dir", str(tmp_path), "timeline", run["id"]])
    timeline = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert timeline[0]["type"] == "run.created"
    assert any(event["type"] == "runtime.model_configuration_required" for event in timeline)
    assert timeline[-1]["type"] == "runtime.model_configuration_required"
