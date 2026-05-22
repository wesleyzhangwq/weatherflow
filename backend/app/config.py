"""Application settings, loaded from environment / .env file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_DIR = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[
            str(_PROJECT_DIR / ".env"),
            str(_BACKEND_DIR / ".env"),
        ],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- LLM (OpenAI-compatible default) -----
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    chat_model: str = Field(default="gpt-4o-mini", alias="CHAT_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")
    # Optional split: chat (e.g. DeepSeek) vs embeddings (e.g. Alibaba DashScope compatible).
    # When empty, ``embed`` uses the same base URL + key as ``chat``.
    embedding_base_url: str = Field(default="", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")

    # ----- Anthropic adapter (reserved) -----
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ----- App -----
    data_dir: str = Field(default=str(_BACKEND_DIR / "data"), alias="DATA_DIR")
    db_filename: str = Field(default="weatherflow.db", alias="DB_FILENAME")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8765, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_allowed_origins: str = Field(
        default="http://127.0.0.1:3000,http://localhost:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )

    # ----- Scheduler -----
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    evening_reflection_cron: str = Field(default="22:00", alias="EVENING_REFLECTION_CRON")
    weekly_review_cron: str = Field(default="sun:21:00", alias="WEEKLY_REVIEW_CRON")
    scheduler_timezone: str = Field(default="local", alias="SCHEDULER_TIMEZONE")

    # ----- Model routing (per-task) -----
    chat_model_state: str = Field(default="", alias="CHAT_MODEL_STATE")
    chat_model_reflection: str = Field(default="", alias="CHAT_MODEL_REFLECTION")
    chat_model_planning: str = Field(default="", alias="CHAT_MODEL_PLANNING")
    chat_model_memory: str = Field(default="", alias="CHAT_MODEL_MEMORY")

    # ----- Provider mode -----
    dev_review_provider_mode: str = Field(
        default="direct",
        alias="DEV_REVIEW_PROVIDER_MODE",
        description="Accepted: direct | mcp | dual",
    )
    wf_github_mcp_command: str = Field(
        default="uv run python -m mcp_servers.weatherflow_github.server",
        alias="WF_GITHUB_MCP_COMMAND",
    )
    wf_calendar_mcp_command: str = Field(
        default="uv run python -m mcp_servers.weatherflow_calendar.server",
        alias="WF_CALENDAR_MCP_COMMAND",
    )
    wf_mcp_tool_timeout_seconds: float = Field(
        default=20.0,
        alias="WF_MCP_TOOL_TIMEOUT_SECONDS",
    )
    wf_mcp_write_tools_enabled: bool = Field(
        default=False,
        alias="WF_MCP_WRITE_TOOLS_ENABLED",
    )

    # ----- GitHub MCP (optional) -----
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    monitored_github_repos: str = Field(
        default="wesleyzhangwq/weatherflow",
        alias="MONITORED_GITHUB_REPOS",
        description="Comma-separated list of repos to monitor (owner/repo format)",
    )

    # ----- Google Calendar MCP (optional) -----
    google_calendar_access_token: str = Field(default="", alias="GOOGLE_CALENDAR_ACCESS_TOKEN")
    google_calendar_token_file: str = Field(default="", alias="GOOGLE_CALENDAR_TOKEN_FILE")
    google_calendar_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_CALENDAR_ID")
    google_calendar_base_url: str = Field(
        default="https://www.googleapis.com/calendar/v3",
        alias="GOOGLE_CALENDAR_BASE_URL",
    )

    # ----- Readable memory -----
    memory_markdown_dir: str = Field(
        default="",
        alias="MEMORY_MARKDOWN_DIR",
        description="Profile Markdown root; default DATA_DIR/memory",
    )

    @property
    def parsed_monitored_repos(self) -> list[tuple[str, str]]:
        """Parse monitored repos from MONITORED_GITHUB_REPOS into list of (owner, repo) tuples."""
        repos: list[tuple[str, str]] = []
        for repo_str in self.monitored_github_repos.split(","):
            parts = repo_str.strip().split("/")
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                repos.append((parts[0].strip(), parts[1].strip()))
        return repos or [("wesleyzhangwq", "weatherflow")]  # fallback

    @property
    def db_path(self) -> str:
        data_dir = Path(os.path.expandvars(self.data_dir)).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / self.db_filename)

    @property
    def resolved_memory_markdown_dir(self) -> str:
        if self.memory_markdown_dir.strip():
            return str(Path(os.path.expandvars(self.memory_markdown_dir)).expanduser())
        return str(Path(os.path.expandvars(self.data_dir)).expanduser() / "memory")

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]
        return origins or ["http://127.0.0.1:3000", "http://localhost:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
