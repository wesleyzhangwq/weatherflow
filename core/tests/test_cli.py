import json

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
    assert stored["status"] == "succeeded"
    assert stored["result_summary"] == "Echo: Explain WeatherFlow"


def test_timeline_command_outputs_ordered_events(tmp_path, capsys) -> None:
    main(["--data-dir", str(tmp_path), "run", "Hello"])
    run = json.loads(capsys.readouterr().out)

    exit_code = main(["--data-dir", str(tmp_path), "timeline", run["id"]])
    timeline = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert timeline[0]["type"] == "run.created"
    assert any(
        event["type"] == "run.status_changed" and event["payload"].get("to") == "succeeded"
        for event in timeline
    )
    assert [event["type"] for event in timeline[-2:]] == [
        "rhythm.signal.task_behavior",
        "rhythm.snapshot_derived",
    ]
