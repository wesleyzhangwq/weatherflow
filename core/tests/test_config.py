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
