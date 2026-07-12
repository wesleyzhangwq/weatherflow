from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
