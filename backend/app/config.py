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

    # ----- LLM (OpenAI-compatible) -----
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    chat_model: str = Field(default="gpt-4o-mini", alias="CHAT_MODEL")
    chat_temperature: float = Field(default=0.4, alias="CHAT_TEMPERATURE")
    # Whether the gateway understands MiniMax's `thinking` param (used to turn
    # reasoning OFF for JSON-mode calls). "auto" = detect from base_url; the
    # param is gateway-specific and some OpenAI-compatible APIs 400 on it.
    llm_thinking_control: str = Field(default="auto", alias="LLM_THINKING_CONTROL")

    # ----- Networking -----
    # Comma-separated hosts to exclude from the system HTTP(S) proxy. On
    # machines where a local proxy (Clash/V2Ray…) MITMs domestic API domains
    # with a self-signed cert, LLM/embedding calls fail intermittently with
    # CERTIFICATE_VERIFY_FAILED — list those API hosts here to force direct
    # connections. Appended to NO_PROXY at startup; leave empty if your LLM
    # endpoint actually needs the proxy.
    no_proxy_hosts: str = Field(default="", alias="NO_PROXY_HOSTS")

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

    # ----- Single user (v1 hard-codes 'default') -----
    default_user_id: str = Field(default="default", alias="DEFAULT_USER_ID")
    timezone: str = Field(default="local", alias="TIMEZONE")

    # ----- Scheduler (T2 every 6 hours, fixed slots) -----
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    # 00:00, 06:00, 12:00, 18:00 local; overridable via env.
    scheduled_check_hours: str = Field(
        default="0,6,12,18", alias="SCHEDULED_CHECK_HOURS"
    )
    # 12-hour fallback heartbeat for DelayedMemoryWriter
    memory_writer_interval_hours: int = Field(
        default=12, alias="MEMORY_WRITER_INTERVAL_HOURS"
    )

    # ----- MCP servers -----
    wf_github_mcp_command: str = Field(
        default="uv run python -m mcp_servers.weatherflow_github.server",
        alias="WF_GITHUB_MCP_COMMAND",
    )
    wf_calendar_mcp_command: str = Field(
        default="uv run python -m mcp_servers.weatherflow_calendar.server",
        alias="WF_CALENDAR_MCP_COMMAND",
    )
    wf_mcp_tool_timeout_seconds: float = Field(
        default=20.0, alias="WF_MCP_TOOL_TIMEOUT_SECONDS"
    )
    # MCP server-side safety switch. Default true because Backend already
    # gates write tools via the Proposal flow (ADR D19) — the MCP-side switch
    # is defence-in-depth, not the primary control. Set false to dry-run
    # everything (useful for offline debugging without touching real services).
    wf_mcp_write_tools_enabled: bool = Field(
        default=True, alias="WF_MCP_WRITE_TOOLS_ENABLED"
    )

    # ----- GitHub -----
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    monitored_github_repos: str = Field(
        default="wesleyzhangwq/weatherflow",
        alias="MONITORED_GITHUB_REPOS",
    )

    # ----- Google Calendar -----
    google_calendar_access_token: str = Field(default="", alias="GOOGLE_CALENDAR_ACCESS_TOKEN")
    google_calendar_token_file: str = Field(default="", alias="GOOGLE_CALENDAR_TOKEN_FILE")
    google_calendar_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_CALENDAR_ID")
    google_calendar_base_url: str = Field(
        default="https://www.googleapis.com/calendar/v3",
        alias="GOOGLE_CALENDAR_BASE_URL",
    )

    # ----- Profile.md (L3) -----
    memory_markdown_dir: str = Field(default="", alias="MEMORY_MARKDOWN_DIR")

    # ----- ContextLoader -----
    bundle_token_budget: int = Field(default=8000, alias="BUNDLE_TOKEN_BUDGET")

    # ----- ReAct loop -----
    rhythm_agent_max_turns: int = Field(default=8, alias="RHYTHM_AGENT_MAX_TURNS")

    # ----- DelayedMemoryWriter thresholds -----
    dmw_section_cooldown_hours: int = Field(default=24, alias="DMW_SECTION_COOLDOWN_HOURS")
    dmw_pattern_window_days: int = Field(default=14, alias="DMW_PATTERN_WINDOW_DAYS")
    dmw_pattern_min_count: int = Field(default=3, alias="DMW_PATTERN_MIN_COUNT")
    dmw_min_confidence: float = Field(default=0.6, alias="DMW_MIN_CONFIDENCE")

    # ----- Proposal expiry -----
    proposal_expiry_hours: int = Field(default=24, alias="PROPOSAL_EXPIRY_HOURS")

    # ----- v2: Semantic memory (L2.5 / mem0 + Qdrant) -----
    qdrant_url: str = Field(default="http://127.0.0.1:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="weatherflow_memories", alias="QDRANT_COLLECTION")
    # L3-fast profile layer (ADR-006): a SEPARATE mem0 collection written with
    # infer=True (consolidated traits), kept apart from the episodic source-
    # linked `qdrant_collection` so it never pollutes the critic-checked evidence.
    qdrant_profile_collection: str = Field(
        default="weatherflow_profile", alias="QDRANT_PROFILE_COLLECTION"
    )
    profile_consolidation_enabled: bool = Field(
        default=True, alias="PROFILE_CONSOLIDATION_ENABLED"
    )
    mem0_api_key: str = Field(default="", alias="MEM0_API_KEY")
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-v4", alias="EMBEDDING_MODEL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_base_url: str = Field(default="", alias="EMBEDDING_BASE_URL")
    # Vector dimension of the embedding model (Ali text-embedding-v3/v4 = 1024,
    # OpenAI text-embedding-3-small = 1536). Must match the Qdrant collection.
    embedding_dims: int = Field(default=1024, alias="EMBEDDING_DIMS")
    semantic_recall_limit: int = Field(default=5, alias="SEMANTIC_RECALL_LIMIT")
    # Hypothesis card cap: keep only the latest N hypothesis events; older ones
    # are physically pruned from L1 (deviation from append-only — see
    # event_log.delete / DECISIONS-v2). Raise this to keep DMW pattern-learning
    # and past-rhythm recall working on more history.
    hypothesis_keep_limit: int = Field(default=3, alias="HYPOTHESIS_KEEP_LIMIT")

    # ----- v2: LangGraph -----
    graph_checkpoints_db: str = Field(default="graph_checkpoints.db", alias="GRAPH_CHECKPOINTS_DB")

    # ----- v2: Observability (Langfuse) -----
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://127.0.0.1:3000", alias="LANGFUSE_HOST")
    otel_exporter: str = Field(default="console", alias="OTEL_EXPORTER")

    # ----- v2: Desktop proactivity -----
    proactivity_enabled: bool = Field(default=True, alias="PROACTIVITY_ENABLED")

    @property
    def supports_thinking_param(self) -> bool:
        """Whether to send MiniMax's `thinking` param. 'on'/'off' force it;
        'auto' enables it only for MiniMax gateways (others may 400 on it)."""
        ctl = self.llm_thinking_control.strip().lower()
        if ctl == "on":
            return True
        if ctl == "off":
            return False
        return "minimax" in self.openai_base_url.lower()

    @property
    def parsed_monitored_repos(self) -> list[tuple[str, str]]:
        repos: list[tuple[str, str]] = []
        for repo_str in self.monitored_github_repos.split(","):
            parts = repo_str.strip().split("/")
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                repos.append((parts[0].strip(), parts[1].strip()))
        return repos

    @property
    def parsed_scheduled_check_hours(self) -> list[int]:
        out: list[int] = []
        for h in self.scheduled_check_hours.split(","):
            h = h.strip()
            if h.isdigit():
                hour = int(h)
                if 0 <= hour < 24:
                    out.append(hour)
        return sorted(set(out)) or [0, 6, 12, 18]

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
        origins = [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]
        return origins or ["http://127.0.0.1:3000", "http://localhost:3000"]

    @property
    def graph_checkpoints_path(self) -> str:
        data_dir = Path(os.path.expandvars(self.data_dir)).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / self.graph_checkpoints_db)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
