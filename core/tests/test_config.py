from pathlib import Path

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
