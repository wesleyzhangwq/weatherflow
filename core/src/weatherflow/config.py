from ipaddress import ip_address
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BUNDLED_SKILL_CATALOG_ROOT = Path(__file__).resolve().parent / "resources" / "wesley-skills"


class Settings(BaseSettings):
    """Process configuration for the local WeatherFlow daemon."""

    model_config = SettingsConfigDict(
        env_prefix="WF_",
        extra="ignore",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Path("~/.local/share/weatherflow").expanduser()
    log_level: str = "INFO"
    bridge_token: str | None = None
    skill_catalog_root: Path = BUNDLED_SKILL_CATALOG_ROOT

    @field_validator("host")
    @classmethod
    def host_is_loopback(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "localhost":
            return normalized
        try:
            address = ip_address(normalized)
        except ValueError as error:
            raise ValueError("daemon host must be a loopback address") from error
        if not address.is_loopback:
            raise ValueError("daemon host must be a loopback address")
        return normalized

    @field_validator("data_dir")
    @classmethod
    def expand_data_directory(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("bridge_token")
    @classmethod
    def configured_bridge_token_is_nonempty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("bridge token cannot be empty")
        return value
