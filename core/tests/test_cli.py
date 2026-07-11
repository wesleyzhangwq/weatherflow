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
        "log_level": "info",
    }


def test_parser_requires_a_command_without_version() -> None:
    parser = build_parser()

    args = parser.parse_args(["serve", "--port", "9000", "--reload"])

    assert args.command == "serve"
    assert args.port == 9000
    assert args.reload is True
