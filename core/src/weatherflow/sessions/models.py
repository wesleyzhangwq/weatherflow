from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ulid import ULID


class ConversationSession(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    id: str
    workspace_id: str
    title: str = Field(min_length=1, max_length=160)
    pinned: bool = False
    latest_run_id: str | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("title")
    @classmethod
    def normalized_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized

    @classmethod
    def new(cls, *, workspace_id: str, title: str = "新对话") -> "ConversationSession":
        now = datetime.now(UTC)
        return cls(
            id=str(ULID()),
            workspace_id=workspace_id,
            title=title,
            created_at=now,
            updated_at=now,
        )


class SessionArtifactBlob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    relative_path: str


class ConversationSessionDeletion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    workspace_id: str
    run_ids: tuple[str, ...]
    artifacts: tuple[SessionArtifactBlob, ...]
