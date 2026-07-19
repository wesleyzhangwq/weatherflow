from pathlib import Path

import pytest

from weatherflow.config import BUNDLED_SKILL_CATALOG_ROOT, Settings


def test_v3_does_not_load_the_legacy_repository_dotenv(tmp_path: Path, monkeypatch) -> None:
    legacy_data = tmp_path / "legacy-data"
    (tmp_path / ".env").write_text(f"WF_DATA_DIR={legacy_data}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WF_DATA_DIR", raising=False)

    settings = Settings()

    assert settings.data_dir == Path("~/.local/share/weatherflow").expanduser()
    assert settings.data_dir != legacy_data


def test_default_skill_catalog_is_bundled_with_weatherflow() -> None:
    settings = Settings()

    assert settings.skill_catalog_root == BUNDLED_SKILL_CATALOG_ROOT
    assert (settings.skill_catalog_root / "skills").is_dir()
    assert (settings.skill_catalog_root / "docs" / "skills-list.md").is_file()
    assert (settings.skill_catalog_root / "docs" / "imports").is_dir()
    assert (settings.skill_catalog_root / "licenses").is_dir()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "weatherflow.example"])
def test_daemon_rejects_non_loopback_bind_addresses(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        Settings(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_daemon_accepts_loopback_bind_addresses(host: str) -> None:
    assert Settings(host=host).host == host


@pytest.mark.parametrize("token", ["", "   "])
def test_configured_bridge_token_cannot_be_empty(token: str) -> None:
    with pytest.raises(ValueError, match="bridge token"):
        Settings(bridge_token=token)


def test_environment_data_directory_expands_the_user_home(monkeypatch) -> None:
    monkeypatch.setenv("WF_DATA_DIR", "~/weatherflow-test-data")

    settings = Settings()

    assert settings.data_dir == Path.home() / "weatherflow-test-data"


def test_activitywatch_defaults_are_loopback_and_read_only_source_locations() -> None:
    settings = Settings()

    assert settings.activitywatch_api_url == "http://127.0.0.1:5600/api/0"
    assert settings.activitywatch_database_path == (
        Path.home()
        / "Library"
        / "Application Support"
        / "activitywatch"
        / "aw-server-rust"
        / "sqlite.db"
    )


def test_activitywatch_database_path_expands_the_user_home(monkeypatch) -> None:
    monkeypatch.setenv("WF_ACTIVITYWATCH_DATABASE_PATH", "~/activitywatch-test/sqlite.db")

    settings = Settings()

    assert settings.activitywatch_database_path == Path.home() / "activitywatch-test/sqlite.db"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:5600/api/0",
        "http://localhost:5600/api/0",
        "http://127.0.0.1:5601/api/0",
        "http://192.168.1.10:5600/api/0",
        "http://activitywatch.example/api/0",
        "http://user:secret@127.0.0.1:5600/api/0",
        "http://127.0.0.1:5600/api/0?token=secret",
        "http://127.0.0.1:5600/api/0#fragment",
    ],
)
def test_activitywatch_api_url_must_be_plain_loopback_http(url: str) -> None:
    with pytest.raises(ValueError, match="ActivityWatch API URL"):
        Settings(activitywatch_api_url=url)
