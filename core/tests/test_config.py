from pathlib import Path

from weatherflow.config import Settings


def test_v3_does_not_load_the_legacy_repository_dotenv(tmp_path: Path, monkeypatch) -> None:
    legacy_data = tmp_path / "legacy-data"
    (tmp_path / ".env").write_text(f"WF_DATA_DIR={legacy_data}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WF_DATA_DIR", raising=False)

    settings = Settings()

    assert settings.data_dir == Path("~/.local/share/weatherflow").expanduser()
    assert settings.data_dir != legacy_data
